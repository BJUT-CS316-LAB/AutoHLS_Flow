import os
import sys
import argparse
import argcomplete
import ast
import code_generation
import extract
import analysis as analysis_
import pickle
import memoryBound
import memoryBoundSplit
import iscc
import subprocess
import parse_vitis_report
import pocc
import code_gen.main as code_gen
import utilities
import splitKernel
import ressources 

# AMPL_CMD = "/home/spouget/ampl.linux-intel64/ampl"
AMPL_CMD = "ampl"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Code Generation")
    parser.add_argument("--file", type=str, help="kernel.c")
    parser.add_argument("--schedule", type=str, nargs='+', help="Schedule e.g., \"[[0,0,0], [1,1,0]]\"")
    parser.add_argument("--UB", type=str, nargs='+', help="UB e.g., [12, 12]")
    parser.add_argument("--LB", type=str, nargs='+', help="LB e.g., [12, 12]")
    parser.add_argument("--statements", type=str, nargs='+', help="Statements e.g. '[\"a+=b\", \"a+=c\"]'")
    parser.add_argument("--iterators", type=str, nargs='+', help="iterators e.g. '[\"i\", \"j\"]'")
    parser.add_argument("--headers", type=str, nargs='+', help="headers e.g. '[\"i\", \"j\"]'")
    parser.add_argument("--arguments", type=str, nargs='+', help="arguments e.g. '[\"i\", \"j\"]'")
    parser.add_argument("--pragmas", type=str, nargs='+', help="pragmas e.g. '[\"\", \"pipeline;unroll factor=8\", \"pipeline\"]'")
    parser.add_argument("--name_function", type=str, help="Name function")
    parser.add_argument("--pragmas_top", action="store_true", help="Is the pragma above the loop (True), by default is False")
    parser.add_argument("--csim", action="store_true", help="Launch CSIM")
    parser.add_argument("--update_shape", action="store_true", help="Update Shape")
    parser.add_argument("--ap_multiple_burst", action="store_true", help="Is array partitioning have to be multiple of burst")
    parser.add_argument("--allow_multiple_transfer", action="store_true", help="allow_multiple_transfer")
    parser.add_argument("--graph_partitioning", action="store_true", help="Launch CSIM")
    parser.add_argument("--vitis", action="store_true", help="Launch Vitis-HLS")
    parser.add_argument("--no_distribution", action="store_true", help="Launch Vitis-HLS")
    parser.add_argument("--print_summary", action="store_true", help="Print Summary of the Report")
    parser.add_argument("--not_optimize_burst", action="store_true", help="Remove the optimization for the burst. Default=False")
    parser.add_argument("--reuse_nlp", action="store_true", help="Remove the optimization for the burst. Default=False")
    parser.add_argument("--not_cyclic_buffer", action="store_true", help="Remove the cyclic buffer optimization. Default=False")
    parser.add_argument("--code_generation", action="store_true", help="Remove the cyclic buffer optimization. Default=False")
    parser.add_argument("--output", type=str, help="Name of the output file")
    parser.add_argument("--SLR", type=int, default=0, help="Number of SLR. Default is 3")
    parser.add_argument("--onnx_file", type=str, help="ONNX file to parse instead of C file")
    parser.add_argument("--factor", type=float, default=0, help="factor. Default is 1")
    parser.add_argument("--partitioning_max", type=int, default=0, help="Number of SLR. Default is 3")
    parser.add_argument("--MAX_BUFFER_SIZE", type=int, default=0, help="Number of SLR. Default is 3")
    parser.add_argument("--MAX_UF", type=int, default=0, help="Number of SLR. Default is 3")
    parser.add_argument("--ON_CHIP_MEM_SIZE", type=int, default=0, help="Number of SLR. Default is 3")
    parser.add_argument("--DSP", type=int, default=0, help="Number of SLR. Default is 3")
    parser.add_argument("--device", type=str, default=None, help="Target device profile (e.g., AC7t1500)")


    parser.add_argument("--folder", type=str, default="hls_output", help="Name of the folder to store the files. Default is 'hls_output'")
    argcomplete.autocomplete(parser)
    args = parser.parse_args()

    output = f"{args.folder}/src/output.cpp"
    host_name = f"{args.folder}/src/host.cpp"
    # os.system(f"rm -rf hls_output")
    os.makedirs(args.folder, exist_ok=True)
    os.makedirs(f"{args.folder}/tmp", exist_ok=True)
    os.makedirs(f"{args.folder}/src", exist_ok=True)
    os.makedirs(f"{args.folder}/tcl_scripts", exist_ok=True)

    os.system(f"cp script/constrain_blocks.tcl {args.folder}/tcl_scripts")
    os.system(f"cp script/phys_opt_loop.tcl {args.folder}/tcl_scripts")
    os.system(f"cp script/print_CR.tcl {args.folder}/tcl_scripts")
    os.system(f"cp script/hls_pre.tcl {args.folder}/tcl_scripts")
    os.system(f"cp script/post_place_qor.tcl {args.folder}/tcl_scripts")
    os.system(f"cp script/print_CR_utilization.tcl {args.folder}/tcl_scripts")

    os.system(f"cp script/vitis.tcl {args.folder}/src")
    os.system(f"cp script/csim.tcl {args.folder}/src")

    os.system(f"cp script/hls_run.sh {args.folder}/")
    os.system(f"cp script/Makefile {args.folder}/")
    os.system(f"cp script/build.tcl {args.folder}/")
    os.system(f"cp script/hls_config_slr0.cfg {args.folder}/")
    os.system(f"cp script/xcl2* {args.folder}/src")

    nlp_file = f"{args.folder}/nlp.mod"
    nlp_log = f"{args.folder}/nlp.log"

    if args.onnx_file:
        import onnx_frontend
        nodes = onnx_frontend.parse_onnx_to_hls(args.onnx_file)
        
        schedule = []
        dic = {}
        operations = []
        operation_list = []
        arrays_size = {}
        dep = []
        
        for id_statement, node in enumerate(nodes):
            iterators_list = [b[0] for b in node.loop_bounds]
            sched_entry = [id_statement]
            for it in iterators_list:
                sched_entry.append(it)
                sched_entry.append(0)
            pragma = ["" for _ in iterators_list]
            schedule.append([f"S{id_statement}", sched_entry, pragma])
            
            op_dict = {"+": 0, "-": 0, "*": 0, "/": 0}
            op_list = []
            for op in op_dict.keys():
                count = node.computation.count(op)
                op_dict[op] += count
                for _ in range(count):
                    op_list.append(op)
            operations.append(op_dict)
            operation_list.append(op_list)
            
            for inp, shape in node.inputs:
                arrays_size[inp] = shape
            for out, shape in node.outputs:
                arrays_size[out] = shape
                
            LB_dict = {}
            UB_dict = {}
            TC_dict = {}
            for b in node.loop_bounds:
                LB_dict[b[0]] = b[1]
                UB_dict[b[0]] = b[2] - 1  # upper bound is inclusive in AutoHLS_Flow
                TC_dict[b[0]] = b[2] - b[1]
                
            dic[id_statement] = {
                "read": node.read_access,
                "write": node.write_access,
                "statement_body": node.computation,
                "TC": TC_dict,
                "LB": LB_dict,
                "UB": UB_dict,
                "LB_": LB_dict,
                "UB_": UB_dict,
                "constraint": []
            }
        iscc_ = None
    else:
        if not args.no_distribution:
            schedule, dic, operations, arrays_size, dep, operation_list = extract.compute_statement(args.folder, args.file)
            iscc_ = iscc.ISCC(args.no_distribution, args.folder, schedule, dic, operations, arrays_size, dep, operation_list)
        else:
            os.system(f"cp {args.file} {args.folder}/new.cpp")
            f = open(f"{args.folder}/new.cpp", "r")
            lines = f.readlines()
            f.close()
            for i in range(len(lines)):
                if "void" in lines[i] and "(" in lines[i] and ")" in lines[i]:
                    lines[i] = f"void kernel_nlp(" + lines[i].split("(")[1]
                    break
            f = open(f"{args.folder}/new.cpp", "w")
            f.writelines(lines)
            f.close()


        schedule, dic, operations, arrays_size, dep, operation_list = extract.compute_statement(args.folder, f"{args.folder}/new.cpp")


    analysis = analysis_.Analysis(schedule, dic, operations, arrays_size, dep, operation_list)
    UB = analysis.UB
    LB = analysis.LB
    statements = analysis.statements
    iterators = analysis.iterators
    schedule = analysis.only_schedule
    
    headers = ['ap_int.h', 'hls_stream.h', 'hls_vector.h', 'cstring'] 
    arguments = []
    # compute cte

    if not args.onnx_file:
        f = open(args.file, "r")
        lines = f.readlines()
        f.close()

        for line in lines:
            if "void" in line and "(" in line and ")" in line:
                cte = line.split("(")[1].split(")")[0].split(",")
                for cc in cte:
                    if "[" not in cc:
                        arguments.append(cc)
                break

    arguments += analysis.arguments
    name_function = "kernel_nlp"
    pragmas = [[] for k in range(len(UB))]
    pragmas_top = False

    res = ressources.Ressources()
    if args.device == "AC7t1500":
        res.SLR = 3
        res.ON_CHIP_MEM_SIZE = 25559040  # 195 Mb in bytes
        res.DSP = 2560  # MLP blocks
        res.factor = 1.0
        print(f"[Device Config] Loaded Achronix AC7t1500 profile: SLR={res.SLR}, Mem={res.ON_CHIP_MEM_SIZE} bytes, DSP={res.DSP}")

    if args.SLR != 0:
        res.SLR = args.SLR
    if args.factor != 0:
        res.factor = args.factor
    if args.partitioning_max != 0:
        res.partitioning_max = args.partitioning_max
    if args.MAX_BUFFER_SIZE != 0:
        res.MAX_BUFFER_SIZE = args.MAX_BUFFER_SIZE
    if args.MAX_UF != 0:
        res.MAX_UF = args.MAX_UF
    if args.ON_CHIP_MEM_SIZE != 0:
        res.ON_CHIP_MEM_SIZE = args.ON_CHIP_MEM_SIZE
    if args.DSP != 0:
        res.DSP = args.DSP

    res.DSP_per_SLR = int(res.DSP/res.SLR)
    res.BRAM_per_SLR = int(res.BRAM/res.SLR)
    res.MEM_PER_SLR = int(res.ON_CHIP_MEM_SIZE/res.SLR)

    if not args.reuse_nlp:
        if args.graph_partitioning:
            split = splitKernel.Identify("new.cpp", nlp_file, analysis, schedule, UB, LB, statements, iterators, output, headers, arguments, name_function, pragmas, pragmas_top)
            memoryBoundSplit.memoryBound(res, args.folder, split, "new.cpp", nlp_file, analysis, schedule, UB, LB, statements, iterators, output, headers, arguments, name_function, pragmas, pragmas_top)
            utilities.run_ampl_py(args.folder, "nlp.mod", "nlp.log")
            splitKernel.splitKernel("new.cpp", nlp_file, analysis, schedule, UB, LB, statements, iterators, output, headers, arguments, name_function, pragmas, pragmas_top)
        else:
            memoryBound.memoryBound(res, args.folder, args.allow_multiple_transfer, args.ap_multiple_burst, "new.cpp", nlp_file, analysis, schedule, UB, LB, statements, iterators, output, headers, arguments, name_function, pragmas, pragmas_top)
            utilities.run_ampl_py(args.folder, "nlp.mod", "nlp.log")



    code_gen.code_gen(args.update_shape, res.SLR, nlp_file, nlp_log, args.file, output, host_name, schedule, analysis)

    try:
        os.system(f"clang-format -i {output}")
    except:
        pass

    for id_slr in range(res.SLR):
        try:
            os.system(f"clang-format -i {output.replace('output.cpp', f'slr{id_slr}.cpp')}")
        except:
            pass

    h_file = output.split(".")[0] + ".h"
    try:
        os.system(f"clang-format -i {h_file}")
    except:
        pass
    try:
        os.system(f"clang-format -i {host_name}")
    except:
        pass

    try:
        os.system(f"clang-format -i {host_name.replace('host.cpp', 'csim.cpp')}")
    except:
        pass
    

    print("Files generated in", args.folder + "/")
    # Run Vitis-HLS if specified
    if args.csim:
        utilities.run_vitis_hls("csim.tcl",f"{args.folder}/src")

    if args.vitis:
        utilities.run_vitis_hls("vitis.tcl", f"{args.folder}/src")
        cycles, gf, DSP_utilization, BRAM_utilization, LUT_utilization, FF_utilization, URAM_utilization = utilities.print_summary(args.folder, args.file)