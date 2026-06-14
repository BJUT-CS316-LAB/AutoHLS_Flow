# AutoHLS_Flow: Automatic HLS Optimization and Code Generation Framework

AutoHLS_Flow is a holistic toolchain for automatic code generation for FPGA accelerators. It supports both High-Level Synthesis (HLS) from affine C/C++ kernels and direct mapping from ONNX neural network models, leveraging mathematical optimization techniques to generate efficient hardware implementations.

## ✨ Key Features

- Direct parsing and mapping of **ONNX models** to optimized HLS-C++ pipelines.
- Support for **affine C/C++ kernels** with static loop bounds.
- Automatic **loop scheduling**, **pragmas insertion**, and **code generation**.
- Integration with **AMPL** for **Nonlinear Programming (NLP)**-based resource allocation.
- Generation of optimized **HLS-C++** and **host code**.
- Simulation and synthesis with **AMD Vitis HLS**.

---

## 🚀 Quick Start

### 1. Requirements

- Python 3.8+
- AMPL (path configured in `main.py`)
- Clang-format (for formatting the output code)
- AMD Vitis HLS (for synthesis and CSIM)

To run the framework seamlessly with PoCC, ISCC, AMPL, and Gurobi dependencies, we provide a pre-configured Docker image.

**1. Pull the Docker Image:**

```bash
docker pull ryanzhang511/autohls_flow_image:latest
```

**2. Start the Docker Container:**

You must map your local directory to the container and provide your AMPL license UUID via an environment variable.

```bash
docker run -it -d \
  --name autohls_flow_container \
  -v /path/to/your/AutoHLS_Flow:/AutoHLS_Flow \
  -e AMPL_LIC_UUID="<your-ampl-license-uuid>" \
  ryanzhang511/autohls_flow_image:latest \
  /bin/bash
```

**3. Enter the Container:**

```bash
docker exec -it autohls_flow_container /bin/bash
cd /AutoHLS_Flow
```

### 2. Example Usage

**Example A: Generating HLS from an ONNX Model**

```bash
python main.py \
  --onnx_file dummy_deit.onnx \
  --SLR 3 \
  --DSP 1440 \
  --MAX_BUFFER_SIZE 512 \
  --ON_CHIP_MEM_SIZE 8192 \
  --MAX_UF 32 \
  --code_generation \
  --folder hls_output_onnx
```

**Example B: Generating HLS from an Affine C/C++ Kernel**

```bash
python main.py \
  --file examples/gemm.c \
  --vitis \
  --csim \
  --SLR 3 \
  --DSP 1440 \
  --MAX_BUFFER_SIZE 512 \
  --ON_CHIP_MEM_SIZE 8192 \
  --MAX_UF 32 \
  --code_generation \
  --folder hls_output_c
```

## ⚙️ Command-Line Arguments

| Argument                 | Description                                                                 |
|--------------------------|-----------------------------------------------------------------------------|
| `--file`                 | Path to the input C/C++ kernel                                              |
| `--folder`               | Output folder for generated code and reports (default: `hls_output`)        |
| `--name_function`        | Kernel function name (default: `kernel_nlp`)                               |
| `--SLR`                  | Number of available Super Logic Regions                                    |
| `--DSP`                  | Total number of available DSP slices                                       |
| `--BRAM`, `--FF`, `--LUT`| FPGA resource budgets (optional)                                           |
| `--MAX_BUFFER_SIZE`      | Maximum allowed on-chip buffer size per array                             |
| `--ON_CHIP_MEM_SIZE`     | Total available on-chip memory                                             |
| `--MAX_UF`               | Maximum loop unrolling factor                                              |
| `--reuse_nlp`            | Use previously computed NLP results                                        |
| `--vitis`                | Enable synthesis using AMD Vitis HLS                                       |
| `--csim`                 | Enable C simulation with Vitis HLS                                         |
| `--code_generation`      | Enable output of HLS-C++ and host code                                     |
| `--graph_partitioning`   | Enable graph partitioning across SLRs or compute units                     |
| `--no_distribution`      | Disable ISCC-based loop distribution                                       |
| `--update_shape`         | Automatically update shape-related constraints                             |
| `--ap_multiple_burst`    | Enable multiple AXI burst access inference                                 |
| `--cyclic_buffer`        | Use cyclic buffering strategy for data reuse                               |
| `--verbose`              | Print detailed information during execution                                |
| `--debug`                | Enable debug mode                                                          |
