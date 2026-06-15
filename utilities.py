import os
from subprocess import run, PIPE, CalledProcessError
import re
import pocc
import parse_vitis_report

def run_ampl(AMPL, fold):
    os.system(f"cd {fold} && {AMPL} nlp.mod > nlp.log 2>&1")

def run_ampl_py(folder, nlp_file="nlp.mod", nlp_log="nlp.log", lic_uuid=None):
    """Run AMPL model using amplpy instead of an external ampl binary.

    This expects that amplpy is installed and that either:
    - lic_uuid is provided explicitly, or
    - the AMPL_LIC_UUID environment variable is set.
    """
    from amplpy import AMPL, modules

    if lic_uuid is None:
        lic_uuid = os.environ.get("AMPL_LIC_UUID")
    if lic_uuid is None:
        raise RuntimeError("AMPL_LIC_UUID environment variable not set and no lic_uuid provided for run_ampl_py().")

    # 使用 amplpy 调用 AMPL，并用 getOutput 捕获所有终端输出，
    # 然后手动写入 nlp_log，这样可以 100% 保证 log 文件内容
    # 和你在终端看到的一致，而无需依赖 AMPL 自己的 log_file 机制。
    modules.activate(lic_uuid)
    ampl = AMPL()

    nlp_path = os.path.abspath(os.path.join(folder, nlp_file))
    log_path = os.path.abspath(os.path.join(folder, nlp_log))

    # AMPL 命令里路径要用双引号包裹，注意转义。
    safe_nlp = nlp_path.replace("\\", "/").replace('"', '\\"')
    cmd = f'model "{safe_nlp}";'

    # 通过 getOutput 执行命令并抓取所有输出（包括 Gurobi 日志、display 结果等）。
    out = ampl.getOutput(cmd)

    # 把输出写到 nlp_log 文件中。
    with open(log_path, "w") as f:
        f.write(out)

    if "infeasible" in out.lower() or "objective" not in out.lower():
        print("[错误日志] 求解器未能找到可行解 (Infeasible Problem)。\n很可能是由于您提供的约束（如 --ON_CHIP_MEM_SIZE 或其它资源限制）太小所导致。\n您可以到控制台检查输出或放宽参数重试！")
        import sys
        sys.exit(1)


def process_nlp_results(schedule, nlp_file, nlp_log):
    with open(nlp_log, "r") as f:
        log_lines = f.readlines()
    with open(nlp_file, "r") as f:
        nlp_lines = f.readlines()

    results = {}
    objective_seen = False
    for line in log_lines:
        if "Objective" in line:
            objective_seen = True
        if objective_seen and "=" in line:
            key, value = line.replace(" ", "").strip().split("=")
            if "_total_solve_time" in line:
                results[key] = float(value)
            else:
                try:
                    results[key] = int(value)
                except ValueError:
                    results[key] = int(float(value))

    order_array = {}
    for line in log_lines:
        if "Lat_comm" in line:
            key, value = line.replace(" ", "").strip().split("=")
            key = key.replace("Lat_comm_", "")
            order_array[key] = ""

    for line in nlp_lines:
        if "var" in line and "perm" in line and "cost" not in line:
            var = line.split()[1].replace(";", "")
            id_stat = int(var.split("_")[1].replace("S", ""))
            if results[var] == 1:
                tup = eval(line.split("#")[-1])
                for j in range(1, len(schedule[id_stat]), 2):
                    schedule[id_stat][j] = tup[j//2]

    for line in nlp_lines:
        if "#comment" in line:
            array = line.split()[2]
            perms = [results[perm] for perm in line.split("permutation")[-1].split("have")[0].replace(" ", "").split("*")]
            sched_array = eval(line.split("order")[-1].replace(" ", "").strip())
            if sum(perms) == len(perms):
                order_array[array] = sched_array

    return results, order_array


def generate_final_code(original_file):
    generate_code_computation.GenerateCodeComputation(original_file, "nlp.mod", "nlp.log")


def organize_files(folder, files_to_move):
    os.makedirs(folder, exist_ok=True)
    
    for file in files_to_move:
        os.system(f"mv {file} sisyphus/")


import subprocess
import shutil

def run_vitis_hls(tcl_file, path):
    """
    Run the Vitis HLS command with the specified TCL file in the given path.
    
    Parameters:
        tcl_file (str): The TCL file to run.
        path (str): The working directory for the command.
        
    Returns:
        None
    """

    # 优先使用环境变量 HLS_CMD 指定的命令，例如：
    #   export HLS_CMD="vitis-run --mode hls"
    # 否则按顺序尝试：vitis_hls（旧版），vitis-run --mode hls（2025.1+）。
    hls_cmd = os.environ.get("HLS_CMD")
    cmd_parts = None
    if hls_cmd:
        cmd_parts = hls_cmd.split()
    else:
        if shutil.which("vitis_hls") is not None:
            cmd_parts = ["vitis_hls"]
        elif shutil.which("vitis-run") is not None:
            # 新版 2025.1+：vitis-run --mode hls -f csim.tcl
            cmd_parts = ["vitis-run", "--mode", "hls"]
        else:
            raise FileNotFoundError("No HLS command found: neither 'vitis_hls' nor 'vitis-run'. Set HLS_CMD to your HLS command, e.g. 'vitis-run --mode hls -f'.")

    # vitis_hls 用 "vitis_hls tcl.tcl" 调用；vitis-run 需要 "vitis-run --mode hls --tcl tcl.tcl"。
    if "vitis-run" in cmd_parts[0] or (hls_cmd and "vitis-run" in hls_cmd):
        command = cmd_parts + ["--tcl", tcl_file]
    else: 
        command = cmd_parts + [tcl_file]
    
    try:
        # Execute the command
        result = subprocess.run(
            command,
            cwd=path,
            capture_output=True,
            text=True,
            check=True
        )
        # Print the standard output
        print("Command Output:")
        print(result.stdout)
        print(f"{tcl_file} run successful!")
    
    except subprocess.CalledProcessError as e:
        # Print error details
        print(f"Error while running {tcl_file}:")
        print("Stdout Output:")
        print(e.stdout)
        print("Error Output:")
        print(e.stderr)
        print("Return Code:", e.returncode)
        print("Command Executed:", e.cmd)
        print("Please ensure the environment is correctly configured and try running 'ulimit -s unlimited' before executing the command.")
    
    except Exception as ex:
        # Catch any other exceptions
        print(f"An unexpected error occurred: {ex}")


def print_summary(folder, source_file):
    report_file = f"{folder}/src/kernel_nlp/solution/syn/report/kernel_nlp_csynth.rpt"
    cycles, DSP_utilization, BRAM_utilization, LUT_utilization, FF_utilization, URAM_utilization = parse_vitis_report.parse_vitis(report_file)
    flops = pocc.extract_flops(f"tmp/{source_file}")
    gf = float(flops) / float(cycles) * 0.250

    print(f"Cycles: {cycles}")
    print(f"GF/s: {gf}")
    print(f"DSP utilization: {DSP_utilization} %")
    print(f"BRAM utilization: {BRAM_utilization} %")
    print(f"LUT utilization: {LUT_utilization} %")
    print(f"FF utilization: {FF_utilization} %")
    print(f"URAM utilization: {URAM_utilization} %")
    print("You can find the reports in the folder ./kernel_nlp/solution/syn/report/")
    return cycles, gf, DSP_utilization, BRAM_utilization, LUT_utilization, FF_utilization, URAM_utilization

def read_file(file_path):
    with open(file_path, "r") as file:
        return file.readlines()

def write_file(file_path, lines):
    with open(file_path, "w") as file:
        file.writelines(lines)

def delete_lines_containing(name_file, substrings):
    lines = read_file(name_file)
    filtered_lines = [line for line in lines if not any(sub in line for sub in substrings)]
    write_file(name_file, filtered_lines)

def delete_pragma(name_file):
    delete_lines_containing(name_file, ["#pragma"])

def delete_comment(name_file):
    lines = read_file(name_file)
    filtered_lines = []
    skip = False
    for line in lines:
        if "/*" in line:
            skip = True
        if not skip:
            filtered_lines.append(line)
        if "*/" in line:
            skip = False
    write_file(name_file, filtered_lines)

def delete_register(name_file):
    delete_lines_containing(name_file, ["register"])

def delete_pragma_scop(name_file):
    delete_lines_containing(name_file, ["#pragma scop", "#pragma endscop"])

def delete_include(name_file):
    delete_lines_containing(name_file, ["#include"])

def add_pragma_scop(name_file):

    file_ = open(name_file, "r")
    lines = file_.readlines()
    file_.close()
    os.system(f"rm {name_file}")

    # 找第一个真正的 for 循环行：
    #   - 必须匹配 "for (" 或 "for(" 这样的 for 语句语法
    #   - 必须跳过多行注释块 /* ... */ 内的行
    #   - 不含 void（排除函数签名）
    first_for = None
    in_block_comment = False
    for k in range(len(lines)):
        stripped = lines[k].strip()
        # 检测进入/退出多行注释块
        if "/*" in stripped:
            in_block_comment = True
        if "*/" in stripped:
            in_block_comment = False
            continue
        if in_block_comment:
            continue
        # 跳过单行注释
        if stripped.startswith("//"):
            continue
        # 匹配真正的 for 语句（for( 或 for (），并排除函数签名
        if re.search(r'\bfor\s*\(', lines[k]) and "void" not in lines[k]:
            first_for = k
            break

    # 找函数体最后一个 "}" 的行（作为 #pragma endscop 的插入位置）
    last_acc = 0
    for k in range(len(lines)):
        if "}" in lines[k]:
            last_acc = k

    if first_for is not None:
        # 先插 #pragma endscop（在后面，先插不影响 first_for 的索引）
        lines.insert(last_acc, "#pragma endscop\n")
        # 再插 #pragma scop（在第一个 for 循环之前）
        lines.insert(first_for, "#pragma scop\n")
    else:
        # 没有 for 循环时，退回到函数体第一个 "{" 之后插入
        first_acc = 0
        for k in range(len(lines)):
            if "{" in lines[k] and lines[k].count("{") <= 1:
                first_acc = k
                break
        lines.insert(last_acc, "#pragma endscop\n")
        lines.insert(first_acc + 1, "#pragma scop\n")

    file_ = open(name_file, "w")
    for line in lines:
        file_.write(line)
    file_.close()

def add_pragma_scop_generic(name_file, func):
    lines = read_file(name_file)
    func(lines)
    first_acc, last_acc = next(i for i, l in enumerate(lines) if "{" in l), max(i for i, l in enumerate(lines) if "}" in l)
    for_ = any("for" in line for line in lines)
    if for_:
        first_acc = next(i for i, l in enumerate(lines) if "for" in l)
    lines.insert(last_acc, "#pragma endscop\n")
    lines.insert(first_acc + 1, "#pragma scop\n")
    write_file(name_file, lines)

def add_pragma_scop_intertile(name_file):
    add_pragma_scop_generic(name_file, lambda lines: [line for i, line in enumerate(lines) if "void" in line])

def add_pragma_scop_intratile(name_file):
    add_pragma_scop_generic(name_file, lambda lines: [line for i, line in enumerate(lines) if "void" in line])

def replace_define(name_file):
    lines = read_file(name_file)
    defines = {line.split()[1]: line.split()[2] for line in lines if line.startswith("#define")}
    content = "".join(line for line in lines if not line.startswith("#define"))
    for var, val in defines.items():
        content = content.replace(var, val)
    write_file(name_file, content)

def add_pragma_kernel(name_file):
    lines = read_file(name_file)
    if any("#pragma ACCEL kernel" in line for line in lines):
        return
    pos_void = next(i for i, line in enumerate(lines) if "void" in line)
    lines.insert(pos_void, "#pragma ACCEL kernel\n")
    write_file(name_file, lines)

def launch(cmd):
    return run(cmd, stdout=PIPE, stderr=PIPE, universal_newlines=True, shell=True).stdout.split("\n")

def compute_number_of_statement(name_file):
    sentence = "[Pluto] Number of statements:"
    res = launch(f"pocc --pluto --verbose {name_file} -n")
    return next(int(line.split(":")[1]) for line in res if sentence in line)

def compute_number_of_tile(name_file):
    trace_pocc = launch(f"pocc {name_file} --verbose --pluto-fuse maxfuse --pluto-tile -n")
    begin_tiling = next(i for i, line in enumerate(trace_pocc) if "[Pluto] After tiling:" in line)
    end_tiling = next(i for i, line in enumerate(trace_pocc) if "[Pluto] using CLooG" in line)
    tilable_loop = {trace_pocc[k].split()[0] for k in range(begin_tiling + 1, end_tiling) if "tLoop" in trace_pocc[k]}
    return len(tilable_loop)

def compute_cloogl_cloof(name_file):
    trace_pocc = launch(f"pocc {name_file} --verbose --pluto-fuse maxfuse --pluto-tile -n")
    line = next(line for line in trace_pocc if "[Pluto] using CLooG -f/-l options:" in line)
    cloogf, cloogl = line.split(":")[1].strip().split()
    return cloogf, cloogl

def delete_bracket(name_file):
    lines = read_file(name_file)
    bracket_positions = [(i, line.count("{"), line.count("}")) for i, line in enumerate(lines)]
    open_brackets = 0
    delete_positions = []
    for i, open_b, close_b in bracket_positions:
        open_brackets += open_b - close_b
        if open_brackets == 1 and "{" in lines[i] and not any(keyword in lines[i] for keyword in ["for", "if"]):
            delete_positions.append(i)
            for j in range(i, len(lines)):
                if lines[j].count("}") > 0:
                    delete_positions.append(j)
                    break
    write_file(name_file, [line for i, line in enumerate(lines) if i not in delete_positions])

def replace_intra_tile(name_file, name_file_intra_tile):
    lines = read_file(name_file)
    lines_intra = read_file(name_file_intra_tile)
    void_positions = [i for i, line in enumerate(lines) if "void" in line]
    combined_lines = lines[:min(void_positions)] + lines_intra + lines[max(void_positions):]
    write_file(name_file, combined_lines)

def write_back_def(file_, defi):
    lines = read_file(file_)
    first_bracket = next(i for i, line in enumerate(lines) if "{" in line)
    write_file(file_, lines[:first_bracket + 1] + [defi] + lines[first_bracket + 1:])

def find_sizeof(cfile):
    lines = read_file(cfile)
    return 64 if any("double" in line for line in lines) else 32

def rename_register(name_file):
    lines = read_file(name_file)
    write_file(name_file, [line.replace("register", "") for line in lines])

def change_name_variable(file_):
    lines = read_file(file_)
    loops = []
    nb_loop = 0
    for k, line in enumerate(lines):
        if "for" in line:
            iterator = line.split("(")[1].split("=")[0].strip()
            new_name = f"i{nb_loop}"
            loops.append((iterator, new_name))
            nb_loop += 1
    for old_name, new_name in loops:
        lines = [re.sub(fr'\b{old_name}\b', new_name, line) for line in lines]
    iterators = ", ".join(new_name for _, new_name in loops)
    first_for = next(i for i, line in enumerate(lines) if "for" in line)
    lines.insert(first_for, f"int {iterators};\n")
    write_file(file_, lines)

def extract_iteration_domain(cfile):
    new_file = f"tmp/.tmp_id{os.path.basename(cfile)}"
    os.system(f"cp {cfile} {new_file}")
    delete_pragma(new_file)
    add_pragma_scop(new_file)
    lines = pocc.scop(new_file)
    ID, parameters = [], []
    for k, line in enumerate(lines):
        if "# Parameter names" in line:
            params = lines[k + 1].split()
            parameters.extend([p for p in params if not p.isdigit()])
        if "= Statement " in line:
            nb_elmt = int(lines[k + 4].split()[0])
            tmp_str = [lines[i].split("##")[-1][:-1].replace("==", "=") for i in range(k + 5, k + 5 + nb_elmt) if "fakeiter" not in lines[i]]
            ID.append(" and ".join(tmp_str))
    os.system(f"rm {new_file}")
    return ID, parameters
