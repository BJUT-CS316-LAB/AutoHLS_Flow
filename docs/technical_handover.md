# AutoHLS_Flow 技术交底文档

> **版本**: v1.0 | **最后更新**: 2026-06-14 | **许可证**: Apache 2.0

---

## 1. 项目概述

### 1.1 这个项目是做什么的？

AutoHLS_Flow 是一个**自动化的 FPGA 加速器代码生成框架**。它的核心能力是：

1. 接受一个**C/C++ 仿射循环内核**（如矩阵乘法 GEMM）或一个 **ONNX 神经网络模型**作为输入。
2. 通过**多面体编译**（Polyhedral Compilation）技术分析循环结构和数据依赖。
3. 使用**非线性规划**（NLP）数学优化求解器（AMPL + Gurobi）来自动决定最优的循环分块、展开因子、片上缓存分配等硬件参数。
4. 自动生成面向 **AMD Vitis HLS** 的优化 C++ 代码，包括 HLS Kernel、Host 代码、TCL 脚本和 Makefile。

**一句话总结**：给它一段算法代码或一个神经网络模型 + 目标 FPGA 的硬件约束，它就能自动输出可综合的、经过优化的 HLS 工程。

### 1.2 核心技术栈

| 技术 | 用途 |
|------|------|
| **Python 3.8+** | 主框架语言 |
| **PoCC** (多面体编译器) | 分析 C 代码的循环迭代域、数据依赖、调度 |
| **ISCC** (Integer Set Calculator) | 验证循环变换的合法性（依赖关系保持） |
| **AMPL + Gurobi** | 数学优化求解器，求解资源分配的 NLP 问题 |
| **AMD Vitis HLS 2025.1** | 将生成的 C++ 代码综合为 RTL (Verilog) |
| **Docker** | 封装以上所有工具链的运行环境 |

---

## 2. 项目目录结构

```
AutoHLS_Flow/
├── main.py                  # ★ 主入口，解析命令行参数并驱动整个流程
├── onnx_frontend.py         # ONNX 模型前端：将 .onnx 文件转为内部表示
├── extract.py               # 从 C 文件中提取语句、循环域、数据访问
├── parser.py                # 解析 PoCC 输出的调度信息
├── pocc.py                  # PoCC 工具的 Python 封装接口
├── iscc.py                  # ISCC 工具的封装：循环分布与依赖验证
├── analysis.py              # 分析模块：判断计算/访存瓶颈，选择最优调度
├── memoryBound.py           # ★ 核心 NLP 建模模块（单内核模式）
├── memoryBoundSplit.py       # ★ 核心 NLP 建模模块（图分割模式）
├── splitKernel.py           # 内核分割识别（跨 SLR 分割分析）
├── ressources.py            # FPGA 资源定义（DSP、BRAM、片上存储等）
├── utilities.py             # 工具函数集合（AMPL 调用、Vitis HLS 调用等）
├── code_generation.py       # 中间代码生成（循环变换后的 C 代码）
├── parse_vitis_report.py    # 解析 Vitis HLS 综合报告
│
├── code_gen/                # ★ 最终 HLS 代码生成子模块
│   ├── main.py              #   代码生成入口
│   ├── code_generation_dataflow.py   # Dataflow 架构代码生成器
│   ├── code_generation_dataflow2.py  # 带形状更新的代码生成器
│   ├── generate_csim.py     #   C 仿真 Testbench 生成器
│   ├── split_per_slr.py     #   按 SLR 拆分内核
│   ├── post_pass.py         #   后处理 Pass（优化生成代码）
│   └── write_tcl.py         #   TCL 脚本生成
│
├── script/                  # ★ 模板文件目录（会被自动复制到输出目录）
│   ├── Makefile             #   HLS IP 构建系统
│   ├── build.tcl            #   Vitis HLS 综合 TCL 脚本
│   ├── hls_config_slr0.cfg  #   HLS 配置文件
│   ├── hls_run.sh           #   全流程运行脚本（编译+链接+仿真）
│   ├── host.cpp             #   Host 端模板代码
│   ├── vitis.tcl            #   Vitis HLS 综合入口 TCL
│   ├── csim.tcl             #   C 仿真 TCL
│   ├── xcl2.cpp / xcl2.hpp  #   Xilinx OpenCL 工具库
│   └── *.tcl                #   各类约束和优化 TCL 脚本
│
├── onnx_files/              # 存放 ONNX 模型文件（已被 .gitignore 忽略）
├── hls_output/              # 默认输出目录（已被 .gitignore 忽略）
├── tmp/                     # 临时文件目录（已被 .gitignore 忽略）
├── README.md                # 项目说明文档
├── LICENSE                  # Apache 2.0 许可证
└── .gitignore               # Git 忽略规则
```

---

## 3. 端到端工作流程

### 3.1 总流程图

```
输入                    前端解析              数学优化               代码生成              HLS 综合
┌──────────┐      ┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────┐
│ C 文件   │─────>│ PoCC + ISCC  │────>│ AMPL/Gurobi  │────>│ code_gen/    │────>│ Vitis    │
│ 或       │      │ 多面体分析    │     │ NLP 求解     │     │ 生成 HLS C++ │     │ HLS      │
│ ONNX模型 │─────>│ ONNX前端解析 │────>│ 资源分配优化  │────>│ + Makefile   │────>│ 综合     │
└──────────┘      └──────────────┘     └──────────────┘     └──────────────┘     └──────────┘
```

### 3.2 详细步骤说明

#### 步骤 1：输入解析

**路径 A — C/C++ 仿射内核输入** (`--file`)

1. `extract.py` 调用 `pocc.py` 对输入的 C 文件运行 PoCC 工具。
2. PoCC 会自动检测 `#pragma scop` / `#pragma endscop` 包围的循环区域（由 `utilities.add_pragma_scop()` 自动插入）。
3. 提取出：
   - **语句体**（如 `C[i][j] += A[i][k] * B[k][j]`）
   - **迭代域**（每个循环变量的上下界）
   - **数据访问模式**（读/写的数组及其下标表达式）
   - **数据依赖**（通过 CANDL 分析得到 RAW/WAW/WAR 依赖）
4. `iscc.py` 使用 ISCC 工具进行**循环分布**探索（尝试将独立的语句分配到不同的循环层级），并通过依赖关系验证合法性。

**路径 B — ONNX 模型输入** (`--onnx_file`)

1. `onnx_frontend.py` 加载 ONNX 模型文件。
2. 提取其中的 **MatMul** 算子节点。
3. 根据张量的形状信息（如 `[197, 768] × [768, 768]`），自动构建等价的仿射循环表示（三层嵌套循环 `i, j, k`）。
4. 生成与 C 文件路径等效的内部数据结构（`HLSNode` 对象），无需经过 PoCC。

#### 步骤 2：分析与调度

`analysis.py` 接收上一步的输出，进行以下分析：

- **计算/访存瓶颈判断**：比较计算量（循环迭代空间大小）与数据量（数组大小），决定该内核是计算密集型还是访存密集型。
- **关键数组识别** (`array_to_focus`)：找出数据量最大的数组，这些数组的片上缓存策略将作为优化的重点。
- **循环排列优化**：枚举所有合法的循环排列顺序，选择使**归约循环不在最内层**的排列（以利于 HLS Pipeline）。

#### 步骤 3：NLP 数学优化求解

这是框架的**核心创新点**。

`memoryBound.py`（或 `memoryBoundSplit.py`，用于图分割模式）负责：

1. **构建 NLP 模型** (`nlp.mod` 文件)：
   - **决策变量**：每个循环的展开因子（Unrolling Factor）、每个数组每个维度的分块大小（Tiling Factor）、循环排列方案等。
   - **目标函数**：最小化总延迟（通信延迟 + 计算延迟）。
   - **约束条件**：
     - DSP 资源约束（展开因子决定并行度，并行度决定 DSP 消耗）。
     - 片上存储约束（分块大小决定片上缓存大小，总和不超过 BRAM/URAM 容量）。
     - 最大缓冲区大小约束。
     - 最大展开因子约束。

2. **调用求解器**：
   - 通过 `amplpy`（AMPL 的 Python API）将 NLP 模型发送给 **Gurobi** 求解器。
   - Gurobi 在给定的硬件资源约束下找到最优的参数分配方案。
   - 求解结果写入 `nlp.log`。

3. **结果提取**：
   - `utilities.process_nlp_results()` 从 `nlp.log` 中提取求解结果（每个循环的最优展开因子、每个数组的最优分块大小等）。

#### 步骤 4：HLS 代码生成

`code_gen/` 子模块根据 NLP 求解结果生成最终的 HLS C++ 代码：

1. **`code_generation_dataflow.py`**：生成基于 **Dataflow** 架构的 HLS C++ 代码。包括：
   - 自动生成 `load_*` / `store_*` 函数（DMA 数据搬运）。
   - 自动生成 `compute_*` 函数（计算内核）。
   - 自动插入 `#pragma HLS DATAFLOW` 和 `#pragma HLS PIPELINE` 等优化指令。
   - 生成 HLS Stream（`hls::stream`）用于函数间数据传递。

2. **`generate_csim.py`**：生成 C 仿真测试激励（Testbench），用于功能验证。

3. **`split_per_slr.py`**：当使用多 SLR 时，将内核按 SLR 拆分成多个独立的 `.cpp` 文件（如 `slr0.cpp`, `slr1.cpp`）。

4. **`post_pass.py`**：后处理优化 Pass，对生成的代码进行最终调整。

5. **模板文件复制**：`main.py` 将 `script/` 目录下的模板文件（Makefile、build.tcl 等）复制到输出目录。

#### 步骤 5：HLS 综合与仿真（可选）

如果指定了 `--csim` 或 `--vitis` 参数：

- `--csim`：调用 Vitis HLS 运行 C 仿真，验证生成代码的功能正确性。
- `--vitis`：调用 Vitis HLS 进行高层次综合，生成 RTL 并输出资源利用报告。

---

## 4. 环境搭建指南（从零开始）

### 4.1 Docker 环境（推荐）

项目提供了预配置好所有依赖的公开 Docker 镜像 `ryanzhang511/autohls_flow_image:latest`。

**第一步：拉取镜像**

直接从 Docker Hub 拉取公开镜像：
```bash
docker pull ryanzhang511/autohls_flow_image:latest
```

*（注：如果您使用的是离线包传输，也可使用 `docker load -i autohls_flow_image.tar.gz` 进行导入）*

**第二步：启动容器**

```bash
docker run -it -d \
  --name autohls_flow_container \
  -v /path/to/your/AutoHLS_Flow:/AutoHLS_Flow \
  -e AMPL_LIC_UUID="<your-ampl-license-uuid>" \
  ryanzhang511/autohls_flow_image:latest \
  /bin/bash
```

参数说明：
| 参数 | 含义 |
|------|------|
| `--name` | 容器名称，方便后续引用 |
| `-v` | 将宿主机的项目目录映射到容器内的 `/AutoHLS_Flow` |
| `-e AMPL_LIC_UUID` | **必须**。AMPL 求解器的许可证 UUID（向项目负责人获取） |

**第三步：进入容器**

```bash
docker exec -it autohls_flow_container /bin/bash
cd /AutoHLS_Flow
```

### 4.2 容器内已预装的工具

| 工具 | 路径 | 用途 |
|------|------|------|
| PoCC | `/opt/pocc/bin/pocc` | 多面体编译 |
| ISCC | `/opt/pocc/math/barvinok/iscc` | 整数集合计算 |
| AMPL + amplpy | Python 包 | 数学建模语言 |
| Gurobi | 通过 AMPL 调用 | NLP 求解器 |
| Vitis HLS 2025.1 | `/opt/Xilinx/2025.1/` | HLS 综合 |
| Merlin Compiler | `/opt/merlin/` | 源到源变换工具 |
| Python 3 | 系统自带 | 运行框架 |

---

## 5. 使用指南

### 5.1 命令行参数完整说明

```bash
python main.py [必选参数] [硬件约束参数] [控制参数] [输出参数]
```

#### 输入参数（二选一）

| 参数 | 类型 | 说明 |
|------|------|------|
| `--file` | 字符串 | C/C++ 仿射内核源文件路径 |
| `--onnx_file` | 字符串 | ONNX 神经网络模型文件路径 |

#### 硬件约束参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--SLR` | 整数 | 1 | FPGA 上 Super Logic Region 的数量 |
| `--DSP` | 整数 | 自动 | 可用 DSP 数量 |
| `--MAX_BUFFER_SIZE` | 整数 | 4096 | 每个数组最大片上缓冲区大小（KB） |
| `--ON_CHIP_MEM_SIZE` | 整数 | 1512000 | 总片上存储大小（字节） |
| `--MAX_UF` | 整数 | 4096 | 最大循环展开因子 |
| `--device` | 字符串 | 无 | 预定义的设备配置（如 `AC7t1500`） |
| `--factor` | 浮点数 | 1.0 | 资源利用率缩放因子 |

#### 控制参数

| 参数 | 说明 |
|------|------|
| `--code_generation` | 启用 HLS C++ 代码生成 |
| `--vitis` | 启用 Vitis HLS 综合 |
| `--csim` | 启用 C 仿真 |
| `--reuse_nlp` | 复用之前的 NLP 求解结果（跳过求解步骤） |
| `--graph_partitioning` | 启用跨 SLR 的图分割优化 |
| `--no_distribution` | 禁用 ISCC 循环分布 |
| `--update_shape` | 启用形状自动更新（使用 dataflow2 生成器） |
| `--ap_multiple_burst` | 启用多 AXI Burst 访问推断 |
| `--allow_multiple_transfer` | 允许多次数据传输 |

#### 输出参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--folder` | `hls_output` | 输出目录名称 |
| `--output` | 自动 | 输出文件名 |

### 5.2 使用示例

#### 示例 A：从 ONNX 模型生成 HLS 代码

```bash
python main.py \
  --onnx_file models/deit_model.onnx \
  --SLR 3 \
  --DSP 1440 \
  --MAX_BUFFER_SIZE 512 \
  --ON_CHIP_MEM_SIZE 8192 \
  --MAX_UF 32 \
  --code_generation \
  --folder hls_output_deit
```

#### 示例 B：从 C 文件生成 HLS 代码并综合

```bash
python main.py \
  --file examples/gemm.c \
  --SLR 3 \
  --DSP 1440 \
  --MAX_BUFFER_SIZE 512 \
  --ON_CHIP_MEM_SIZE 8192 \
  --MAX_UF 32 \
  --code_generation \
  --vitis \
  --csim \
  --folder hls_output_gemm
```

#### 示例 C：复用之前的 NLP 结果（加速迭代）

```bash
python main.py \
  --file examples/gemm.c \
  --reuse_nlp \
  --code_generation \
  --folder hls_output_gemm
```

### 5.3 输出目录结构

运行后，输出目录的结构如下：

```
hls_output/
├── Makefile              # HLS IP 构建 Makefile
├── build.tcl             # Vitis HLS 综合脚本
├── hls_config_slr0.cfg   # HLS 配置
├── hls_run.sh            # 全流程运行脚本
├── nlp.mod               # AMPL 数学模型文件
├── nlp.log               # 求解器输出日志
├── graph.png             # 语句依赖图（调试用）
├── gurobi.log            # Gurobi 求解日志
├── src/
│   ├── output.cpp        # ★ 生成的 HLS 内核代码
│   ├── output.h          # 内核头文件
│   ├── slr0.cpp          # SLR 0 的内核代码（多 SLR 时）
│   ├── csim.tcl          # C 仿真 TCL
│   ├── vitis.tcl         # 综合 TCL
│   ├── k2k.cfg           # Kernel-to-Kernel 配置
│   ├── xcl2.cpp/hpp      # OpenCL 工具库
│   └── ...
├── tcl_scripts/          # Vivado 约束和优化脚本
│   ├── constrain_blocks.tcl
│   ├── phys_opt_loop.tcl
│   └── ...
└── tmp/                  # 临时文件
```

### 5.4 使用 Makefile 进行 HLS 综合

进入输出目录后，可以使用 Makefile 进行 IP 综合：

```bash
cd hls_output

# 查看帮助
make help

# 列出可构建的 IP
make list

# 构建所有 IP
make

# 构建特定 IP
make output
make slr0

# 指定目标设备和频率
make DEVICE=xcu250-figd2104-2L-e FREQ=300

# 清理构建产物
make clean
```

---

## 6. 输入文件格式要求

### 6.1 C/C++ 仿射内核

输入的 C 文件必须满足以下条件：

1. **静态仿射循环边界**：循环的上下界必须是编译时常量或外层循环变量的仿射函数。
2. **仿射数组下标**：数组的访问下标必须是循环变量的仿射表达式。
3. **包含一个 `void` 函数**：框架会自动将函数名重命名为 `kernel_nlp`。

示例（GEMM）：
```c
void gemm(float A[128][128], float B[128][128], float C[128][128]) {
    for (int i = 0; i < 128; i++)
        for (int j = 0; j < 128; j++)
            for (int k = 0; k < 128; k++)
                C[i][j] += A[i][k] * B[k][j];
}
```

### 6.2 ONNX 模型

- 标准的 ONNX 格式文件（`.onnx`）。
- 目前主要支持 **MatMul** 算子的自动映射。
- 如果文件不存在，框架会使用内置的 Mock DeiT Attention 层进行演示。

---

## 7. 核心模块详解

### 7.1 NLP 数学模型 (memoryBound.py)

这是整个框架最核心的模块（约 2400 行），负责将硬件优化问题建模为数学规划问题。

**关键概念**：

- **Trip Count (TC)**：循环的迭代次数。
- **Unrolling Factor (UF)**：循环展开因子，决定硬件并行度。
- **Tiling Factor (TF)**：分块因子，决定片上缓存的大小。
- **Footprint**：一个数据分块在片上占用的存储空间。
- **通信延迟 (Lat_comm)**：数据从片外搬运到片上的延迟。
- **计算延迟 (Lat_comp)**：计算内核执行的延迟。
- **Initiation Interval (II)**：Pipeline 的启动间隔。

**优化目标**：最小化 `max(Lat_comm, Lat_comp)`，即在通信和计算之间达到平衡。

### 7.2 资源模型 (ressources.py)

定义 FPGA 的硬件资源参数：

```python
# 默认配置
sizeof = 32          # 数据位宽 (32-bit float)
SLR = 1              # Super Logic Region 数量
DSP = 9024           # DSP 总数（乘以 factor）
BRAM = 4032          # BRAM 总数
ON_CHIP_MEM_SIZE = 1512000  # 片上存储总量（字节）
MAX_BUFFER_SIZE = 4096      # 单个数组最大缓冲区
MAX_UF = 4096               # 最大展开因子

# DSP 消耗模型（32-bit float）
DSP_per_operation = {"+": 2, "-": 2, "*": 3, "=": 0, "/": 0}

# Pipeline 延迟模型（32-bit float）
IL = {"+": 7, "*": 4, "=": 1, "-": 7, "/": 12}
```

### 7.3 ONNX 前端 (onnx_frontend.py)

将 ONNX 的 MatMul 算子转换为框架内部表示：

```
MatMul(X[M,K], W[K,N]) → Q[M,N]
    ↓
for(i=0; i<M; i++)
  for(j=0; j<N; j++)
    for(k=0; k<K; k++)
      Q[i][j] += X[i][k] * W[k][j];
```

### 7.4 内部数据结构详解

框架内部在各模块间传递的核心数据结构如下（理解它们是读懂源码的关键）：

#### `schedule` — 调度表示

由 `parser.py` 从 PoCC 的 `.scop` 文件中解析得到，格式为：

```python
# 每个元素: [语句ID, 调度向量, pragma列表]
# 调度向量: [词典序位置0, 循环变量0, 词典序位置1, 循环变量1, ...]
schedule = [
    ["S0", [0, "i", 0, "j", 0, "k", 0], ["", "", ""]],
    ["S1", [1, "i", 0, "j", 0],           ["", ""]],
]
# 含义：S0 在词典序第0组，循环嵌套为 i→j→k
#        S1 在词典序第1组，循环嵌套为 i→j
```

偶数位置 `[0], [2], [4]...` 是**词典序常量**（决定语句的执行先后顺序），奇数位置 `[1], [3], [5]...` 是**循环迭代变量名**。

#### `dic` — 语句信息字典

由 `extract.py` 的 `compute_statement()` 函数构建：

```python
dic = {
    0: {  # 语句 S0
        "read":  ["A[i][k]", "B[k][j]"],       # 读访问模式
        "write": ["C[i][j]"],                    # 写访问模式
        "statement_body": "C[i][j]+=A[i][k]*B[k][j];",
        "TC":  {"i": 128, "j": 128, "k": 128},  # Trip Count
        "LB":  {"i": 0,   "j": 0,   "k": 0},    # 下界
        "UB":  {"i": 127, "j": 127, "k": 127},   # 上界（含）
        "LB_": {"i": "0", "j": "0", "k": "0"},   # 符号下界
        "UB_": {"i": "127","j": "127","k": "127"},# 符号上界
        "constraint": ["i>=0", "-i+127>=0", ...]  # 迭代域约束
    }
}
```

#### `HLSNode` — ONNX 前端节点

由 `onnx_frontend.py` 构建，用于 ONNX 路径（跳过 PoCC）：

```python
class HLSNode:
    op_type = "MatMul"
    name = "Attention_Q_Proj"
    inputs  = [("X", [197, 768]), ("Wq", [768, 768])]  # (名称, 形状)
    outputs = [("Q", [197, 768])]
    loop_bounds  = [('i', 0, 197), ('j', 0, 768), ('k', 0, 768)]
    read_access  = ["X[i][k]", "Wq[k][j]"]
    write_access = ["Q[i][j]"]
    computation  = "Q[i][j] += X[i][k] * Wq[k][j];"
```

ONNX 路径在 `main.py:92-146` 将 `HLSNode` 转换为与 C 路径完全相同的 `schedule` + `dic` 格式。

#### `Analysis` 对象

由 `analysis.py` 构建，汇总并规范化所有分析结果：

```python
analysis.only_schedule  # 纯数字调度向量（循环变量替换为全局循环ID）
analysis.UB / LB        # 按全局循环ID索引的上下界列表
analysis.TC             # 按全局循环ID索引的 Trip Count 列表
analysis.iterators      # 按全局循环ID索引的迭代变量名列表
analysis.statements     # 语句体字符串列表
analysis.arguments      # 函数参数列表 (如 ["float A[128][128]", ...])
analysis.arrays_size    # 数组名→维度列表 (如 {"A": [128, 128]})
analysis.is_memory_bound      # bool: 是否访存密集型
analysis.is_computation_bound # bool: 是否计算密集型
analysis.array_to_focus       # 需要重点优化的数组列表
analysis.is_reduction_innermost  # {语句ID: bool} 最内层是否为归约循环
```

**瓶颈判断逻辑**（`analysis.py:162-180`）：
- 计算量 = `max(∏TC[var] for each statement)` （循环迭代空间的乘积）
- 数据量 = `max(∏size[dim] for each array)`
- 若计算量 > 数据量 × 1.05 → 计算密集型；否则 → 访存密集型

### 7.5 函数调用链详解

#### main.py 的完整执行流程（逐行解读）

```
main.py 入口
│
├─ 1. 创建输出目录结构 (L68-71)
│     hls_output/ ── src/
│                 ── tmp/
│                 └─ tcl_scripts/
│
├─ 2. 复制模板文件 (L73-87)
│     script/*.tcl → hls_output/tcl_scripts/
│     script/vitis.tcl, csim.tcl → hls_output/src/
│     script/Makefile, build.tcl → hls_output/
│     script/xcl2.* → hls_output/src/
│
├─ 3. 输入解析（二选一）
│  ├─ A. ONNX路径 (L92-146): onnx_frontend.parse_onnx_to_hls()
│  │     → 构建 schedule, dic, operations, arrays_size
│  └─ B. C文件路径 (L147-165):
│        ├─ 非 no_distribution: extract.compute_statement() + iscc.ISCC()
│        └─ no_distribution: 直接复制文件，重命名函数为 kernel_nlp
│
├─ 4. 分析 (L168): Analysis(schedule, dic, ...)
│     → 瓶颈判断、关键数组识别、循环排列优化
│
├─ 5. 资源配置 (L197-222): Ressources() + 命令行参数覆盖
│     → 计算 DSP_per_SLR, BRAM_per_SLR, MEM_PER_SLR
│
├─ 6. NLP求解 (L224-232，除非 --reuse_nlp)
│  ├─ graph_partitioning 模式:
│  │   splitKernel.Identify() → memoryBoundSplit.memoryBound()
│  │   → utilities.run_ampl_py() → splitKernel.splitKernel()
│  └─ 普通模式:
│      memoryBound.memoryBound() → utilities.run_ampl_py()
│      生成 nlp.mod（AMPL模型）→ 调用 Gurobi → 输出 nlp.log
│
├─ 7. 代码生成 (L236): code_gen.code_gen()
│     ├─ code_generation_dataflow.CodeGeneration()  # 生成 output.cpp
│     ├─ post_pass.GeneratePostPass()                # 后处理优化
│     ├─ generate_csim.CSIM()                        # 生成 csim.cpp
│     └─ split_per_slr.SplitPerSLR()                 # 拆分为 slr0.cpp 等
│
├─ 8. 代码格式化 (L238-262): clang-format（可选，失败不影响）
│
└─ 9. HLS综合/仿真 (L267-272，可选)
      ├─ --csim:  utilities.run_vitis_hls("csim.tcl")
      └─ --vitis: utilities.run_vitis_hls("vitis.tcl")
                  → utilities.print_summary() 输出资源报告
```

#### extract.py 的内部调用链

```
extract.compute_statement(folder, file)
│
├─ compute_size_arrays(file)
│   └─ 解析 void 函数签名中的数组声明 → {"A": [128, 128], ...}
│
├─ utilities.add_pragma_scop(file)
│   └─ 自动在第一个 for 循环前插入 #pragma scop
│      在最后一个 } 前插入 #pragma endscop
│
├─ pocc.candl(folder, file)  → 数据依赖分析
│   └─ 执行: /opt/pocc/bin/pocc file --candl-dep-isl-simp --verbose -n
│      返回 RAW/WAW/WAR 依赖关系
│
├─ utilities.replace_define(file)
│   └─ 将 #define 宏替换为实际值（PoCC不识别宏）
│
├─ pocc.scop(folder, file)  → 提取 SCOP 信息
│   └─ 执行: /opt/pocc/bin/pocc file --output-scop
│      解析 .scop 文件 → 读访问、写访问、迭代域、语句体
│
├─ pocc.compute_schedule(folder, file)  → 提取调度
│   └─ parser.parser(folder, file) → 解析 Scattering function
│
└─ extract_variable_bounds(constraints)
    └─ 从迭代域约束中提取每个变量的上下界和 Trip Count
```

#### iscc.py 循环分布验证

`ISCC` 类在初始化时自动执行 `run_iscc()`：

1. **生成所有可能的语句分布方案**：将 N 个语句分配到不同的词典序位置（如 `[0,0,1]` 表示 S0、S1 在第0组，S2 在第1组）
2. **对每种方案生成 ISCC 脚本**（`iscc.iscc`），内容包括：
   - `Domain`：每个语句的迭代域
   - `Read/Write`：每个语句的读写访问
   - `Schedule`：待验证的调度
   - 计算 `RaW`, `WaW`, `WaR` 依赖，验证 `RaW ⊆ IslBefore`
3. **执行** `/opt/pocc/math/barvinok/iscc < iscc.iscc`
4. **如果三种依赖都被保持**（输出 `True`），则采纳该分布方案

### 7.6 NLP 建模细节 (memoryBound.py)

`memoryBound` 类的 `__init__` 依次执行：

```
memoryBound.__init__()
├─ compute_TC()              # 收集所有循环的 Trip Count
├─ compute_inter_task_dependance()  # 通过 CANDL 分析语句间 RAW 依赖
├─ compute_graph()           # 构建语句依赖 DAG，输出 graph.png
├─ compute_loop_body_independant()  # 判断各语句的循环体是否独立
├─ compute_info_loops()      # 收集每个语句的归约循环、读写数组等信息
└─ create_nlp()              # ★ 生成 nlp.mod 文件
```

#### NLP 模型文件 (nlp.mod) 的结构

```ampl
# ===== 参数（param）=====
param DSP_avail = 9024;           # 可用 DSP 总数
param ON_CHIP_MEM_SIZE = 1512000; # 片上存储总量
param MAX_BUFFER_SIZE = 4096;     # 单数组最大缓冲区
param MAX_UF = 4096;              # 最大展开因子
param TC0_ori = 128;              # 循环0的原始 Trip Count
param IL_par_S0 = 11;             # 语句0的并行指令延迟
param IL_seq_S0 = 7;              # 语句0的串行指令延迟（归约）
param DSP_S0 = 8;                 # 语句0每次执行消耗的DSP数

# ===== 决策变量（var）=====
var TC0 integer >= 128 <= 2048;   # 循环0的（可能padded的）Trip Count
var TC0_0 integer >= 1;           # 循环0外层分块大小
var TC0_1 integer >= 1;           # 循环0内层分块大小（展开因子）
var perm0_S0 binary;              # 语句0是否选择排列方案0
var perm1_S0 binary;              # 语句0是否选择排列方案1
var is_fused_task0_in_SLR_0 binary;  # 任务0是否放在SLR0

# ===== 约束（subject to）=====
# 分块约束：外层×内层 = 总Trip Count
TC0_0 * TC0_1 = TC0;
# 排列互斥：只能选一种排列
perm0_S0 + perm1_S0 = 1;
# SLR分配：每个任务恰好在一个SLR中
is_fused_task0_in_SLR_0 = 1;
# DSP约束：所有任务的DSP总和不超过可用DSP
DSP_S0 * TC0_1 <= DSP_avail;
# 片上存储约束：所有数组的片上footprint总和不超过存储容量
footprint_A + footprint_B + footprint_C <= ON_CHIP_MEM_SIZE;

# ===== 目标函数 =====
minimize Total_Latency: max(Lat_comm, Lat_comp);
# Lat_comm = 数据搬运延迟（由分块大小和AXI带宽决定）
# Lat_comp = 计算延迟（由循环展开因子和Pipeline II决定）
```

**DSP 消耗计算规则**（`ressources.py`）：

| 数据类型 | `+` | `-` | `*` | `=` | `/` |
|----------|-----|-----|-----|-----|-----|
| float32  | 2 DSP | 2 DSP | 3 DSP | 0 | 0 |
| float64  | 3 DSP | 3 DSP | 8 DSP | 0 | 0 |

**Pipeline 延迟 (IL) 模型**：

| 数据类型 | `+` | `-` | `*` | `=` | `/` |
|----------|-----|-----|-----|-----|-----|
| float32  | 7 cycles | 7 cycles | 4 cycles | 1 cycle | 12 cycles |
| float64  | 5 cycles | 5 cycles | 6 cycles | 1 cycle | 12 cycles |

#### AMPL 求解调用 (utilities.py:10-47)

```python
def run_ampl_py(folder, nlp_file, nlp_log, lic_uuid=None):
    from amplpy import AMPL, modules
    # 1. 激活 AMPL 许可证（从环境变量 AMPL_LIC_UUID 获取）
    modules.activate(lic_uuid or os.environ["AMPL_LIC_UUID"])
    # 2. 执行 AMPL 模型
    ampl = AMPL()
    out = ampl.getOutput(f'model "{nlp_path}";')
    # 3. 将所有输出（含 Gurobi 日志和 display 结果）写入 nlp.log
    with open(log_path, "w") as f:
        f.write(out)
    # 4. 检查是否 infeasible
    if "infeasible" in out.lower():
        sys.exit(1)  # 提示用户放宽约束
```

### 7.7 代码生成架构详解 (code_gen/)

#### code_gen/main.py 的调用流程

```python
class code_gen:
    def __init__(self, update_shape, nb_slr, nlp_file, nlp_log, ...):
        # 1. 选择代码生成器
        if update_shape:
            code_generation_dataflow2.CodeGeneration(...)  # 带形状更新
        else:
            code_generation_dataflow.CodeGeneration(...)   # 标准版

        # 2. 后处理 Pass
        post_pass.GeneratePostPass(...)
        #   → create_fct_when_triple_buffer(): 提取三重缓冲区的 if-else
        #     分支，生成独立的 compute_* 函数
        #   → update_slr(): 修正 SLR 分配空洞（如 SLR2 有但 SLR1 没有）
        #   → update_shape(): 可选的形状更新

        # 3. 生成 C 仿真 Testbench（仅 C 文件输入时）
        if cfile is not None:
            generate_csim.CSIM(...)

        # 4. 按 SLR 拆分
        split_per_slr.SplitPerSLR(output, nlp_file, nlp_log, nb_slr)
        #   → 为每个 SLR 生成独立的 slrN.cpp 文件
        #   → 顶层函数名变为 kernel_nlp_slrN
```

#### CodeGeneration 类的内部 AST

`code_generation_dataflow.py` 内部先构建 AST（抽象语法树），再遍历生成代码：

```
AST 结构:
Root
├── Loop (i0: 外层分块循环)
│   ├── Loop (j0: 外层分块循环)
│   │   ├── Loop (i1: 内层分块循环)  ← #pragma HLS unroll
│   │   │   ├── Loop (j1: 内层分块循环)  ← #pragma HLS unroll
│   │   │   │   └── Statement: C[i][j] += A[i][k] * B[k][j];
```

**分块命名规则**：`i0` 是循环 `i` 的外层分块（inter-tile），`i1` 是内层分块（intra-tile）。

**生成的 HLS 代码结构**（output.cpp）：

```cpp
/****************************************************
 This file was automatically generated by AutoHLS_Flow
****************************************************/
#include <ap_int.h>
#include <hls_stream.h>
#include <hls_vector.h>

// 类型定义
typedef hls::vector<float,16> float16;

// ===== DMA 数据搬运函数 =====
void read_A_FT0(...) {
    // 从片外读取数据到片上缓冲区
    // 使用 memcpy 实现 burst 传输
}
void write_C_FT0(...) {
    // 从片上缓冲区写回片外
}

// ===== 计算任务函数 =====
void task_S0_FT0(...) {
    #pragma HLS pipeline II=2
    // 计算内核（含 #pragma HLS unroll）
}

// ===== 层级调度函数 =====
void FT0_level0(...) {
    #pragma HLS dataflow
    read_A_FT0(...);   // 加载数据
    task_S0_FT0(...);  // 计算
    write_C_FT0(...);  // 存回
}

// ===== 顶层函数 =====
extern "C" void kernel_nlp(float* A, float* B, float* C) {
    #pragma HLS interface m_axi port=A
    #pragma HLS interface m_axi port=B
    #pragma HLS interface m_axi port=C
    // 片上缓冲区声明
    float A_buf[TILE_I][TILE_K];
    #pragma HLS array_partition ...
    // 外层分块循环
    for (int i0 = 0; i0 < TC_I_0; i0++) {
        FT0_level0(A, B, C, A_buf, ...);
    }
}
```

**关键 HLS Pragma 说明**：

| Pragma | 作用 | 生成位置 |
|--------|------|----------|
| `#pragma HLS dataflow` | 允许 load/compute/store 流水并行 | FT*_level* 函数 |
| `#pragma HLS pipeline II=N` | 循环流水线化，每N周期发射一次 | 最内层计算循环 |
| `#pragma HLS unroll` | 完全展开循环为并行硬件 | 内层分块循环 (i1, j1) |
| `#pragma HLS array_partition` | 将数组拆分为多个 BRAM 以支持并行访问 | 片上缓冲区声明处 |
| `#pragma HLS interface m_axi` | 将端口映射为 AXI Master 接口 | 顶层函数参数 |

### 7.8 Makefile 与 TCL 构建系统

#### Makefile 工作原理 (`script/Makefile`)

```makefile
# 默认配置
TARGET ?= ip        # 构建目标：ip / syn / sim / cosim / all
DEVICE ?= xcv80-lsva4737-2MHP-e-S  # 目标 FPGA 器件
FREQ ?= 300         # 目标频率 (MHz)

# 自动检测 src/ 下的 .cpp 文件作为 IP 名
CPP_FILES := src/output.cpp $(wildcard src/slr*.cpp)
IP_NAMES := $(basename $(notdir $(CPP_FILES)))
# 例如：output slr0 slr1

# 构建规则：每个 IP 对应一个 build_<ip>.<device> 目录
# 内部调用 vitis-run --mode hls --tcl build.tcl
```

#### build.tcl 的工作机制

通过环境变量 `TARGET`, `DEVICE`, `IPNAME` 接收 Makefile 传入的参数：

```tcl
# 顶层函数名规则：
# - slr* 文件 → set_top kernel_nlp_slrN
# - output 文件 → set_top kernel_nlp
# - 其他 → set_top $ipname

# 执行流程（由 TARGET 控制）：
# sim   → csim_design（C仿真）
# syn   → csynth_design（综合）
# ip    → csynth_design + export_design（导出IP）
# cosim → csynth_design + cosim_design（协同仿真）
# all   → 全部执行
```

#### Vitis HLS 命令适配 (utilities.py:112-168)

框架自动检测 HLS 工具版本：
1. 优先使用环境变量 `HLS_CMD`
2. 尝试 `vitis_hls`（旧版命令）
3. 尝试 `vitis-run --mode hls`（2025.1+ 新命令）

### 7.9 综合报告解析 (parse_vitis_report.py)

解析 Vitis HLS 生成的 `csynth.rpt` 报告文件，提取：

```
报告文件路径: hls_output/src/kernel_nlp/solution/syn/report/kernel_nlp_csynth.rpt

提取的指标:
├─ cycles_max    → 最大延迟周期数
├─ DSP_used/available → DSP 利用率
├─ BRAM_used/available → BRAM 利用率
├─ LUT_used/available → LUT 利用率
├─ FF_used/available → FF 利用率
└─ URAM_used/available → URAM 利用率

性能计算: GF/s = FLOPS / cycles_max × (频率/1GHz)
         其中 FLOPS 由 pocc --polyfeat 提取
```

---

## 8. 常见问题与排障

### Q1: 求解器报 "Infeasible Problem"

**原因**：硬件约束设置得过于严格，求解器无法找到可行解。

**解决**：放宽约束参数，例如增大 `--ON_CHIP_MEM_SIZE`、`--DSP`、`--MAX_BUFFER_SIZE`。

### Q2: PoCC 报错 "scop file not found"

**原因**：输入的 C 文件不满足仿射循环的要求。

**解决**：检查循环边界是否为编译时常量，数组下标是否为循环变量的仿射表达式。

### Q3: clang-format: command not found

**说明**：这不是错误，只是代码格式化工具未安装。生成的代码功能不受影响，只是格式可能不够美观。

### Q4: AMPL_LIC_UUID 未设置

**解决**：在启动 Docker 容器时通过 `-e` 参数传入，或在容器内执行：
```bash
export AMPL_LIC_UUID="your-uuid-here"
```

### Q5: 如何查看 NLP 求解结果？

查看输出目录下的 `nlp.log` 文件，其中包含每个决策变量的最优值。

---

## 9. 开发者须知

### 9.1 添加新的 ONNX 算子支持

在 `onnx_frontend.py` 的 `parse_onnx_to_hls()` 函数中：
1. 在 `graph.node` 的遍历中添加对新算子类型的过滤。
2. 根据算子的语义构建等价的 `HLSNode`，设置 `loop_bounds`、`read_access`、`write_access` 和 `computation`。

### 9.2 添加新的 FPGA 设备配置

在 `main.py` 的设备配置部分添加新的 `if args.device == "新设备名":` 分支，设置对应的 SLR、DSP、片上存储等参数。

### 9.3 Git 分支策略

- `main`：稳定版本
- `lab`：实验室开发分支（当前活跃分支）

---

## 10. 许可证

本项目采用 **Apache License 2.0** 开源许可证。
