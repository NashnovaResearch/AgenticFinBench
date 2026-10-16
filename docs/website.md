# Finance 500 展示页

`site/` 是无框架的静态展示页，包含 12 组冻结质量成绩、500 题搜索和逐题正负项 rubric、评测方法、下载入口与一键运行说明。不调用评测模型，不需要 API key。

```sh
python3 scripts/build_site.py
python3 -m http.server 8765 --bind 127.0.0.1 --directory public
```

访问 `http://127.0.0.1:8765/`。构建从 `data/` 校验冻结哈希并生成 `public/`。Rubric 按题加载，首页不会下载全部约 16 MB 的标准。所有本地链接均为相对路径，可部署在域名根目录或子路径。构建产物不提交 Git。

## 内容维护

- 题目和标准：`data/questions.json`、`data/rubrics.json`、`data/manifest.json`，仍按原评测校验规则维护。
- 最终成绩：`site/results.json`，保留来源摘要 SHA256、各组完成题数和共同 499 题均分。页面只显示最终分数，不展示旧分对比。
- 统计范围：默认各组已完成题目；Trae 与 Dumate 缺少 `en120-120`，是 499/500。共同题集选项使用各组相同的 499 题。
- 成绩来自已冻结回答的增量复核，包含原判定复用，不声明为公开运行器新跑的一轮结果。公开运行器不读取此榜单。
- 首页统计为发布时的冻结规模；如更新数据版本，需要同步核对页面数字和日期。

## GitLab 发布

每次 CI 的 `site-build` 都生成可下载的 `public/` 静态发布包，不安装额外依赖。现有评测校验、SAST 和密钥扫描仍保留。

2026-10-16 实测：当前项目是 Private；当前账号的可见性选择器禁用；部署菜单与项目功能设置均没有 Pages，Pages 管理入口返回 404。因此提交页面代码不等于已获得匿名可访问的网站 URL，不能把仓库 URL 当作展示页 URL。

管理员完成 GitLab Pages 服务、域名和 TLS 配置后：

1. 在项目 CI/CD Variables 设置 `PUBLISH_GITLAB_PAGES=true`（普通非敏感变量）。
2. 运行 `main` 的流水线；`deploy-pages` 自动发布 `public/`。
3. 在 Deploy → Pages 读取实际 URL，并验证未登录访问。
4. 若要允许访客下载 GitLab 仓库，还需由有权限的管理员核对项目/上级组的公开可见性；仅发布网站不会自动公开私有仓库。

如使用其他静态服务器，只需部署 `public/` 内容，无后端、数据库或密钥。禁止将仓库根目录、`.env`、运行回答或评测日志整体作为网站发布目录。

布局参考了 [FinSearchComp](https://randomtutu.github.io/FinSearchComp/) 的研究型页面结构；页面代码、图形与文案独立编写，没有使用其榜单或图片。
