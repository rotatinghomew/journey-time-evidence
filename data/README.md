# 资料字典

时刻使用本地日期内分钟。多个设备的有效校准以所选截止日当时可见的最高修订为准。原始事实不全时使用可证实范围。典型文案门槛按权重达到最低节省的人数份额；返程缓冲从乘客可离开时起至表列接驳发车时止，去程、回程须联合满足对应条件方属于通过的经历。返程推广仅面向去程在 10 时前能启程的行程；以同一份有效时间资料判断该条件和返程缓冲。

## `journeys.json`

用时观测范围及可比旅程条件。

| 字段 | 含义 |
| --- | --- |
| `journey` | 旅程标识 |
| `day` | 出行日 |
| `service` | 交车方式 |
| `version` | 产品口径 |
| `area` | 到访范围 |
| `pickup` | 交车地点类型 |
| `return_kind` | 归还方式 |
| `distance` | 行程公里 |
| `party` | 旅客数 |
| `window` | 出发窗类型 |

## `matched_groups.json`

业务人员提出的候选对照，不作确定匹配结论。

| 字段 | 含义 |
| --- | --- |
| `pair` | 候选配对组 |
| `journey` | 旅程标识 |
| `basis` | 对应范围问题 |
| `weight` | 抽取权重 |

## `timestamps.json`

现场记录给出本地设备同日分钟上下界。

| 字段 | 含义 |
| --- | --- |
| `event` | 事件标识 |
| `journey` | 旅程标识 |
| `kind` | 旅客可用节点 |
| `device` | 记录设备 |
| `clock_min_lo` | 设备时钟分钟下界 |
| `clock_min_hi` | 设备时钟分钟上界 |
| `visible_day` | 可见日 |
| `revision` | 同一事件修订序号 |

## `calibrations.json`

真实分钟等于设备分钟加钟差；同一设备同一日公用一个未知钟差。

| 字段 | 含义 |
| --- | --- |
| `day` | 设备运行日 |
| `device` | 设备标识 |
| `offset_lo` | 钟差下界分钟 |
| `offset_hi` | 钟差上界分钟 |
| `visible_day` | 可见日 |
| `revision` | 校准修订号 |

## `statements.json`

内容席需要证据的宣传草案和签发政策。

| 字段 | 含义 |
| --- | --- |
| `statement` | 文案编号 |
| `claim` | 用途 |
| `minutes` | 最小节省或最短缓冲分钟 |
| `reliability` | 要求的旅客份额 |
| `confidence` | 审核置信等级 |
| `version` | 产品适用版本 |
| `area` | 覆盖地区 |
| `page` | 位置标识 |

## `pages.json`

共享推广位的页面可以有不同访问范围和例外表达能力。

| 字段 | 含义 |
| --- | --- |
| `page` | 位置标识 |
| `route` | 投放位置 |
| `areas` | 可能覆盖地区 |
| `show_exceptions` | 是否能显示范围限制 |
| `accepted` | 已确认过的文案编号 |

## `connections.json`

声明返程余量时的出发截止时间。

| 字段 | 含义 |
| --- | --- |
| `area` | 地区 |
| `window` | 出发条件 |
| `departure` | 回程接驳发车分钟 |
