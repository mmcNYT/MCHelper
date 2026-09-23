---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: '9e0ce77a-4270-4e4e-80f4-94dbb50e372b'
  PropagateID: '9e0ce77a-4270-4e4e-80f4-94dbb50e372b'
  ReservedCode1: '256bf0ce-c7b5-44c0-bd9e-34906a0c7199'
  ReservedCode2: '256bf0ce-c7b5-44c0-bd9e-34906a0c7199'
---

项目阐释：
1.使用pyside6编写
2.程序本身为一个工具合集，使用tab栏进行工具的切换

项目规范：
3.MCHelper为主窗口
4.每个小工具都应该有自己的.py文件来控制
5.被多个工具（Tools/tool_*.py）共用的模块放 Utils/Public/；公共资源（群系图标、EnvSprite、附魔流光等）放 assets/Public/；各工具私有资源放 assets/<工具名>/
6.代码库手册在 Docs/CODEBASE.md（每份源文件的功能/计算流程/函数/接口/变量），结构性调整后同步更新
7.临时测试脚本放 .temp/，用项目 venv 运行；诊断输出写文件再读回

注：
1.每个小工具通过tab栏切换，其本身是依附与主窗口的，不要在添加多余的窗口
2.当我明确说明具体更改位置时，请不要管其它内容
3.每一次更改完文件后，请重新读取一遍文件，确保文件更改准确（非常重要）