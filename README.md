# 每日资讯简报

每天北京时间 20:00，从公开 Google News RSS 抓取政治、AI、娱乐和科学新闻，生成中文分类的 Markdown 简报并发布为 GitHub Issue。新闻标题保留来源的原始语言。

## 特点

- 电脑关机也可运行
- 不需要 OpenAI API Key
- 不需要额外 Python 依赖
- 同一天重复运行时更新已有 Issue，不重复创建
- 工作流仅申请 `contents: read` 和 `issues: write` 权限

## 部署

1. 在 GitHub 创建一个私有仓库。
2. 将本项目中的全部文件上传到仓库根目录。
3. 打开仓库的 **Actions** 页面并启用工作流。
4. 在 **Actions > Daily news briefing > Run workflow** 手动运行一次。
5. 检查仓库的 **Issues** 页面是否生成当天简报。

工作流使用 UTC 时间，配置中的 `0 12 * * *` 对应北京时间每天 20:00。GitHub Actions 的计划任务可能因平台负载延迟数分钟，不保证秒级准时。

## 本地测试

```bash
python -m unittest discover -s tests -v
python scripts/generate_digest.py --output report.md
```

## 调整内容

编辑 `scripts/generate_digest.py` 中的 `CATEGORIES` 可修改新闻分类和检索词；调整工作流中的 `--limit` 可改变每个分类的条目数量。

## 限制

该版本不调用大模型，因此只做权威来源限定、来源加权、去重和排序，不会自动翻译或总结新闻内容。RSS源可能短暂不可用，脚本会跳过失败查询；如果所有来源都为空，工作流会失败并且不会发布空白 Issue。
