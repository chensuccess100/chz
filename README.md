# 每日资讯简报

每天北京时间 20:00，从公开 Google News RSS 抓取政治、AI、娱乐和科学新闻，生成中文分类的 Markdown 简报并发布为 GitHub Issue。新闻标题保留来源的原始语言。

## 特点

- 电脑关机也可运行
- 不需要 OpenAI API Key
- 不需要额外 Python 依赖
- 同一天重复运行时更新已有 Issue，不重复创建
- 配置QQ邮箱后，可同时把完整简报发送到一个或多个邮箱
- 工作流仅申请 `contents: read` 和 `issues: write` 权限

## 部署

1. 在 GitHub 创建一个私有仓库。
2. 将本项目中的全部文件上传到仓库根目录。
3. 打开仓库的 **Actions** 页面并启用工作流。
4. 在 **Actions > Daily news briefing > Run workflow** 手动运行一次。
5. 检查仓库的 **Issues** 页面是否生成当天简报。

## 配置QQ邮箱发送

1. 登录QQ邮箱，在邮箱设置中开启 **IMAP/SMTP服务**，按页面提示生成SMTP授权码。
2. 打开GitHub仓库的 **Settings > Secrets and variables > Actions**。
3. 点击 **New repository secret**，依次创建：

| Secret | 内容 |
| --- | --- |
| `SMTP_USERNAME` | 用于发信的完整QQ邮箱地址，例如 `123456@qq.com` |
| `SMTP_PASSWORD` | QQ邮箱生成的SMTP授权码，不是QQ登录密码 |
| `MAIL_TO` | 收件邮箱；多个地址使用英文逗号分隔 |

4. 打开 **Actions > Daily news briefing > Run workflow** 手动测试一次。
5. 查看收件箱和垃圾邮件目录，并确认当天的GitHub Issue仍正常生成。

不要把SMTP授权码写入代码、Issue或聊天消息。未配置上述Secrets时，邮件步骤会安全跳过，不影响Issue生成。

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
