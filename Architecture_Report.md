# Prometheus 自动化 HLS 优化框架：项目架构与运行原理报告

## 一、 项目背景与概述

Prometheus 是一个面向 Xilinx Versal 等底层硬件平台的高层抽象与自动化硬件部署框架。该项目基于多面体编译模型（Polyhedral Model），可通过解析 C 语言源码计算循环最优多层 tiling (分块) 维度与并行调度。随后基于约束求解引擎 (AMPL/Gurobi) 推导出最佳调度方案，并自动生成带有最佳 HLS（高层次综合）Pragma 配置的 C++ 源码。在后期流程中，框架基于 `SLASH` (v80++) 和 `AVED 25.1` 工具链完成了 IP 核心集成验证及 PDI 流水线部署。

---

## 二、 核心机制与原理 (Underlying Principles)

Prometheus 框架从 C 源码到最终硬件映射，具有一套自成体系的流化机制。它的核心基石可以分为以下三大架构原理：

### 1. 多面体调度与循环分块挖掘 (Polyhedral Scheduling)
- **依赖分析与提取：** 框架使用类似于底层 ISL (Integer Set Library) 的引擎或抽象语法树映射来解析源 C 程序的访问依赖关系。
- **约束求解与划分：** 依靠自带的 AMPL 模型以及 Gurobi 优化求解器计算出循环的分块深度，最终得到每个循环层级的迭代提取因子（即输出的 `TCxxxx_0`, `TCxxxx_1` 等数据）。这一步决定了硬件端每个运算模块并行度的天花板。
- **静态化天花板：** 硬件流水线需要完全确定的资源空间分配，因此多面体引擎必须能在静态编译期计算出极限尺寸（用于 HLS #pragma ARRAY_PARTITION 等）。

### 2. 深度 Dataflow 架构映射与任务融合引擎 (Fused Task Template)
传统的嵌套循环难以在硬件流水线中藏匿通信延迟，因此 Prometheus 强制引入了**数据流（Dataflow）架构**，即“循环融合-任务切割（Loop Fusion and Split）”：
- **从整体到粒度：** 将全局大循环切割并且聚合成细粒度的运算级任务节点—— **Fused Task (FT)** 模块。
- **层级划分：** 打破传统的循环壁垒，重构执行逻辑为两条平行的维度：
  - **Inter-tile（L1 计算块外）：** 将全局通信和读写挪到上层，各个细粒度模块级任务（FT）之间，或者源数据到 FT 之间基于 **HLS Stream (AXI-Stream FIFO)** 通过管道传递数据。这相当于架设了“公路网”。
  - **Intra-tile（L2/L3 计算块内）：** 任务接收到数据流后，在其封装的运算函数 (`taskX_intra`) 内部安全地展开细粒度局部运算。 

### 3. Ping-Pong 缓存机制与通信隐藏 (Ping-Pong Buffering)
在读取端和写入端（如 `load_vA_xxx` 到 `read_xxx_FT`），由于吞吐周期的差异，直接读写会导致硬件握手堵塞（类似前文提到的 Deadlock 瓶颈源）：
- 框架为每个子任务单元配备了 Ping-Pong 双缓冲甚至三缓冲区（代码中实例化的 `A_0`, `A_1` 等局部状态矩阵）。
- 这种机制隔离了**全局读取请求总线**（Global Fetch）与**局部数据消耗（Local Consume）**，使得上层 DMA 读取进程可以在预写入数组 `A_1` 时，计算引擎正在消化 `A_0`。只要读写控制端的维度解除强耦合（即接收器不再强行用局部的多维维度死锁全局读端），流水线就能达到完全满载的理论极值。

---

## 三、 当前核心项目结构说明 (Repository Layout)

```text
/BJUT_LAB/Prometheus
├── main.py                     # 全局 Pipeline 的主控入口，负责驱动各个流水线环节
├── parser.py                   # C 语言源码解析器，负责将源码抽取为 AST 或内部依赖字典
├── generate_nlp.py / launch.py # 生成 AMPL 模型的输入配置文件并驱动 Gurobi 求解器 
├── analysis.py                 # 分析 AST，负责读写矩阵追踪和算子执行依赖深度分析
├── polyhedro.py / iscc.py      # 调用或对齐多面体/ISL集合处理库，产生访存空间的边界映射
├── memoryBound.py              # 对运算空间、片内存分配的内存带宽和上限边界建立数学评估模型
├── generate_code_computation.py# C++ 逻辑核心代码生成器，用于组装 intra-task 计算块并映射语句
├── code_gen/                   # HLS 数据流及结构化 C++ 生成相关核心目录
│   └── code_generation_dataflow.py # Dataflow 控制生成器 (定义了 FIFO, Ping-Pong 映射与 Fused Task 组装规则)
├── cfile/                      # 源 C 算法文件目录（如 symm, gemm 算法）
├── script/ & nlp_cfile/        # 用于保存中间调度、依赖求解和 .mod 文件模型
└── write_tcl.py                # 自动生成可供下游 Xilinx 工具链编译流程用的底层 TCL 描述文件脚本
```

---

## 四、 阶段工作成就及遗留的改型路线 (Next Blueprints)

### 1. 成功验证的关键链条
* **调用链条与鲁棒性**：完整重装了底层解析树与 `nlp.mod` 的流转逻辑，修复了多种畸形边界。
* **物理板卡验证**：通过桥接 PDI 生态和构建专用的主机 Host 控制流代码（支持访问操作底层的 Register 参数配置），目前基于 AVED 25.1 已经实现全生命周期贯通试跑。

### 2. 动态参数控制路线图 (Dynamic Parameters Refactoring Blueprint)
现行的 HLS 生成采用深度硬编码，为了实现用户期盼的 “部署一次硬件，参数能在上位机按需调节” ：
- **保留硬边界**：涉及 `HLS ARRAY_PARTITION` 和 `UNROLL` 的底层必须维持最高天花板规格不变（即由多面体计算出的极大规模不妥协）。
- **执行边界剥离**：在 C 语言结构体外挂基于 `s_axilite` 定义的 Scalar 变量作为控制针脚。随后在 Dataflow 每一层次的跳出验证阶段（例如 `code_generation_computation.py` 生成的 `for(int i = 0; i < dynamic_bounds)`），注入用户传输上限实现提前 `break` / 剪枝，以支持动态长度且不违反综合器硬要求。
