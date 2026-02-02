下面给你一份“把 RSSHub 当作本地接口服务使用”的说明，覆盖 **接口结构、路由拼接、鉴权、输出格式、常用全局参数**，并给出 **证监会（CSRC）** 的具体调用示例。

---

## 1) 你本机 RSSHub 的“接口基址”

你现在是本地 Docker 部署，基址就是：

* `http://127.0.0.1:1200`

后续所有路由都在这个基址下面拼接。

---

## 2) 路由调用的基本格式

### 2.1 URL 结构

**通用模板：**

`{BASE_URL}{ROUTE_PATH}?{QUERY_STRING}`

* `BASE_URL`：`http://127.0.0.1:1200`
* `ROUTE_PATH`：来自 RSSHub 文档/路由表，例如 `/csrc/news/...`
* `QUERY_STRING`：可选的查询参数，例如 `key=...&format=atom`

文档也强调：这些参数本质上就是 URL query，可以用 `&` 组合，并且要放在路由路径之后；有些路由还会在路径里自带参数段。([RSSHub][1])

### 2.2 路径参数（Path Params）的理解

RSSHub 文档里常见写法（举例）：

* `/xxx/:id`：`id` 是必填
* `/xxx/:id?`：`id` 可选（末尾 `?` 表示可选）
* `/xxx/:suffix*` 或类似形式：表示可变长度路径（你把后面的多段路径整体塞进去）

---

## 3) 鉴权（你现在最关心的 key 怎么用）

你在 `.env` 里设置了 `ACCESS_KEY` 后，RSSHub 支持两种访问方式：**key** 或 **code**：([RSSHub][2])

### 3.1 直接用 key（推荐）

在订阅地址后面加：

* `?key=你的ACCESS_KEY`

例如：

`http://127.0.0.1:1200/某路由?key=XXXX`

### 3.2 用 code（读者不方便存 key 时用）

`code` 是 `md5(route + ACCESS_KEY)` 的结果（拼接顺序是“路由在前，key 在后”），访问时用：([RSSHub][2])

* `?code=<md5值>`

---

## 4) 输出格式（RSS / Atom / JSON / UMS）

RSSHub 默认输出 RSS 2.0；如果你想指定格式，用 `format` 参数：([RSSHub][1])

* `format=rss`（RSS 2.0）
* `format=atom`
* `format=json`（JSON Feed）
* `format=ums`（RSS3 UMS）

示例：

* `http://127.0.0.1:1200/某路由?format=atom&key=XXXX` ([RSSHub][1])

---

## 5) 常用“全局参数”用法（过滤/编码要点）

### 5.1 过滤参数（filter / filterout 等）

RSSHub 内建了一组过滤参数（支持正则），例如：

* `filter`：过滤 title + description
* `filter_title`、`filter_description`、`filter_author`、`filter_category`
* `filter_time`：按发布时间范围过滤（秒）([RSSHub][1])

排除同理用 `filterout...`。([RSSHub][1])

**关键注意：参数要做完整 URL 编码**，不要依赖浏览器自动编码，否则 `+`、`&` 等字符会把参数解析弄乱。([RSSHub][1])

---

## 6) 证监会（CSRC）路由怎么调用（示例）

在当前 RSSHub 代码里，证监会新闻路由是：

* `/csrc/news/:suffix?` ([GitHub][3])

调用示例（把 `suffix` 换成你要的栏目标识/后缀）：

```text
# RSS 2.0（默认）
http://127.0.0.1:1200/csrc/news/<suffix>?key=<ACCESS_KEY>

# Atom
http://127.0.0.1:1200/csrc/news/<suffix>?format=atom&key=<ACCESS_KEY>

# JSON Feed
http://127.0.0.1:1200/csrc/news/<suffix>?format=json&key=<ACCESS_KEY>
```

---

## 7) 怎么“找路由”与自检

* 最权威方式：直接按 RSSHub 官方文档的分类页面找路由（Government/Finance 等）。
* 另外，一些实例提供 `/rsshub/routes` 之类的路由清单接口（用于查看/检索现有 routes）；但这取决于版本与实现细节。([GitHub][4])

---

如果你把你“想订阅的证监会具体栏目页面 URL / 栏目名”贴出来（比如“新闻发布会/行政处罚/政策文件”那种栏目），我可以按 `suffix` 的规则把你最终应当订阅的完整 URL（含 key、format）直接给你列好。

[1]: https://rsshub.netlify.app/parameter "Parameters | RSSHub"
[2]: https://rsshub-doc.pages.dev/en/install/ "Deployment | RSSHub"
[3]: https://github.com/DIYgod/RSSHub/blob/master/lib/routes/gov/csrc/news.ts?utm_source=chatgpt.com "RSSHub/lib/routes/gov/csrc/news.ts at master"
[4]: https://github.com/DIYgod/RSSHub/issues/20520?utm_source=chatgpt.com "Use build/routes.json instead of scraping many docs pages ..."
