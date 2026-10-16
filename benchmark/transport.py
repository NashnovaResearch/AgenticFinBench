"""Streaming transport: persist every chunk; never turn reasoning into an answer."""
import json
from types import SimpleNamespace
from openai import AsyncOpenAI
from .common import save, require


class ModelRoutingError(ValueError):
    pass


class Backend:
    def __init__(self, key, config, folder):
        self.config, self.folder = config, folder
        self.client = AsyncOpenAI(api_key=key, base_url=config['gateway'], timeout=config['request_timeout'], max_retries=0)

    async def close(self):
        await self.client.close()

    async def complete_detailed(self, *, model, system_prompt, user_prompt, temperature, max_tokens, extra_body=None):
        n = len(list(self.folder.glob('request-*.json'))) + 1
        p = self.folder / f'request-{n:03d}'
        messages = [{'role':'system','content':system_prompt}, {'role':'user','content':user_prompt}]
        save(p.with_suffix('.json'), dict(model=model, messages=messages, max_tokens=max_tokens, thinking='disabled'))
        # Explicit adaptation verified for the ikuncode DS endpoint. Do not rely on
        # a generic reasoning flag; that previously yielded reasoning without body.
        stream = await self.client.chat.completions.create(model=model, messages=messages,
            temperature=temperature, max_tokens=max_tokens, stream=True,
            stream_options={'include_usage':True}, extra_body={'thinking':{'type':'disabled'}})
        parts, finish, models = [], None, set()
        try:
            with p.with_suffix('.jsonl').open('w', buffering=1) as f:
                async for chunk in stream:
                    d = chunk.model_dump(mode='json')
                    f.write(json.dumps(d, ensure_ascii=False)+'\n')
                    if d.get('model'): models.add(d['model'])
                    for c in d.get('choices', []):
                        if c['delta'].get('content'): parts.append(c['delta']['content'])
                        if c.get('finish_reason'): finish = c['finish_reason']
        finally:
            await stream.close()
        text = ''.join(parts)
        save(p.with_name(p.name+'-response.json'), dict(content=text, finish_reason=finish, response_models=sorted(models)))
        require(bool(text.strip()), 'Empty body (reasoning-only output is not a completed response)')
        allowed={model}|set(self.config.get('response_model_aliases',{}).get(model,[]))
        if not models or not models<=allowed:
            raise ModelRoutingError(f'Response model mismatch: {models}')
        return SimpleNamespace(content=text, finish_reason=finish)

    async def complete(self, **kwargs):
        r = await self.complete_detailed(**kwargs)
        require(r.finish_reason == 'stop', 'Truncated response')
        return r.content
