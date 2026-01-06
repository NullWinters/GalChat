# GalChat ~ 对话辅助即时聊天

聊天不再是打字和语音，你可以像 GalGame 一样用选项快捷回复消息！

## Python 模块使用方法
```bash
python OptionsGenerator.py
```
### 参数说明
- `--mode`: 调用的模式，0表示纯文本输入，1表示数据库检索输入，默认为纯文本输入。
- `--input_str`: 在纯文本模式时输入的文本。
- `--user_id`: 数据库检索模式时被给予选项的用户的id。
- `--group_id`: 数据库检索模式时群聊id。
- `--max_messages`: 数据库检索模式时最大读取的消息条数，默认为1。
- `--set_datetime`: 数据库检索模式时从此时间起往回读取历史消息。
### 示例
纯文本输入
```bash
python OptionsGenerator.py --mode 0 --input_str 出云遥（海外）：答辩,第一个上台讲的,下面老师直接来了一句,我没听懂,然后批了一遍
```
数据库检索输入
```bash
python OptionsGenerator.py --mode 1 --user_id 001 --group_id 0001 --max_messages 2 --set_datetime '2026-01-06 18:00:00'
```
终端中以 json 形式输出选项
终端输出示例：
```
{'contents': [{'content': '天啊，这也太尴尬了！第一个上台压力本来就大，老师还这么说。', 'length': 26}, {'content': '老师也太直接了吧！不过第一个讲完也好，后面就不用紧张了。', 'length': 26}, {'content': '抱抱你！答辩 确实很考验心理素质，你已经很棒了！', 'length': 20}, {'content': '这种经历我也有过，老师有时候说话确实挺打击人的。', 'length': 22}, {'content': '至少讲完了！现在可以放松一下了，晚上要不要一起吃点好的？', 'length': 26}], 'length': 5}
```