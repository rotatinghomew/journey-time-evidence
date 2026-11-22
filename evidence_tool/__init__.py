"""旅行产品时间文案的配对证据工具。

模块划分：

* ``records``   —— 资料装载与截止日（as-of）修订选择
* ``engine``    —— 钟差校准、相邻事件顺序与共用钟差下的可行时间区间
* ``matching``  —— 候选配对的可比性核对与配对级净节省
* ``sensitivity`` —— 权重、缺观察与抽样的敏感性
* ``claims``    —— 两类文案（典型节省 / 返程缓冲）的证据评估
* ``publish``   —— 推广位定向规则、覆盖冲突与更正后的复查
"""

__all__ = [
    "records",
    "engine",
    "matching",
    "sensitivity",
    "claims",
    "publish",
]
