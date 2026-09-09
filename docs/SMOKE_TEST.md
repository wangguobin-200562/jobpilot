# JobPilot v1.0 发布前人工 Smoke Test

所有测试只使用虚构简历、虚构 JD 和本人明确愿意沟通的岗位。缺陷报告不得包含 API Key、连接令牌、真实简历、联系方式、Cookie 或聊天正文。

## 准备

1. 安装 `requirements.txt`。
2. 从 `.env.example` 创建本地 `.env`；仅在需要验证 AI 时配置测试 Key。
3. 运行 `streamlit run app.py`。
4. 确认 Streamlit 页面可访问，Local Bridge 自动监听 `127.0.0.1:8765`。
5. 如需看板数据，运行 `python scripts/seed_demo_data.py` 创建虚构记录。

## Resume 与 JD

- [ ] 上传可选中文本的虚构 PDF，确认本地解析结果、页数和字符数正确。
- [ ] 上传虚构 DOCX，确认文本提取正常。
- [ ] 主动点击 AI 分析后生成非空 `CandidateProfile`，手机号和邮箱默认脱敏。
- [ ] 切换页面并 rerun，确认简历状态保留且不会重复调用 AI。
- [ ] 使用虚构 JD 生成结构化 `JobProfile`。
- [ ] 执行 Resume × JD 匹配，确认技能、经验、项目与证据结构有效。
- [ ] 确认最终匹配分数来自 Python，而不是模型原始输出。

## Fast Screening

- [ ] 使用 5–10 条虚构岗位，确认本地预筛先展示，Flash/Pro 结果渐进更新。
- [ ] 确认边界岗位才进入 Pro，未进入深度匹配的岗位不显示伪造精确分数。
- [ ] 再次筛选相同输入，确认缓存复用且没有重复 provider 调用。
- [ ] 单个岗位失败不影响其他岗位完成。

## BOSS Job Capture

- [ ] 在 Chrome Developer Mode 中加载仓库的 `extension/`。
- [ ] Extension 版本与 `manifest.json` 一致。
- [ ] JobPilot 显示 Local Bridge 自动启动；连接令牌默认遮罩。
- [ ] 将当前令牌填入 Extension，确认状态显示“已连接 JobPilot”。
- [ ] 用户本人登录 BOSS 并主动浏览岗位，确认 Extension 连续采集且轻量去重。
- [ ] 回到 JobPilot，确认公司、岗位、地点、薪资、链接和 JD 合理；缺失字段不会终止整批。
- [ ] 确认最多采集 20 条，完整 JD 不进入日志。

## User-confirmed Contact

- [ ] Fast Screening 后确认“建议投/可以投”默认选择正确，用户可自由调整。
- [ ] Extension 未连接时，“开始沟通”按钮不可用，且不会创建 execution。
- [ ] Extension heartbeat 恢复后按钮自动可用，原选择不丢失。
- [ ] 只选择一个本人愿意沟通的岗位，并完成二次确认。
- [ ] 确认任务依次经过 `pending → processing`。
- [ ] Extension 只点击明确可见的“立即沟通”，使用 BOSS 账号默认招呼语。
- [ ] 只有检测到真实会话后，Repository 状态才从 `saved` 更新为 `contacted`。
- [ ] `contacted` 不设置 `applied_at`；未自动发送简历。
- [ ] 验证码、安全验证、额外表单或不确定状态必须进入 `manual_required` 并停止。
- [ ] 不自动回复招聘方，不读取或保存聊天正文。

## Application Tracking

- [ ] Demo 岗位保存、状态更新、备注、筛选和删除确认正常。
- [ ] `saved/contacted/applied/interviewing/offer/closed` 状态兼容。
- [ ] Dashboard 统计与投递管理数据同步。
- [ ] 重启后 SQLite 中的虚构测试数据仍可读取。
- [ ] `python scripts/clear_demo_data.py` 只删除 `source=demo` 的记录。

## Error Boundaries

- [ ] 无 API Key 时应用仍可启动，AI 操作显示简洁配置提示。
- [ ] 空文件、不支持格式、超限文件和无可读文本文件均被本地拒绝。
- [ ] 空、过短或过长 JD 不触发 provider 请求。
- [ ] UI 不显示 Provider 原始响应、SQL 错误或异常堆栈。
- [ ] Extension 不读取 Cookie、密码、Authorization Header 或网站 LocalStorage Token。
- [ ] 不绕过 CAPTCHA、滑块、平台风控或安全验证。

## 发布确认

- [ ] `pytest` 全部通过。
- [ ] `pip check` 无依赖冲突。
- [ ] `.env`、`.browser/`、本地数据库、日志、缓存和连接令牌未进入 Git。
- [ ] README 的版本、测试数量、功能边界和 Extension 流程与代码一致。
