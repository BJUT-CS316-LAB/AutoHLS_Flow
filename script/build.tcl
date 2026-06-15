# ##################################################################################################
# 适配 Vitis 2025.1 的优化版本 (仅语法与合规性优化)
# 说明：本脚本通过环境变量接收参数，以便支持多个 IP：
#   TARGET : ip / syn / sim / cosim / all （默认 ip）
#   DEVICE : 器件名称（默认 xcv80-lsva4737-2MHP-e-S）
#   IPNAME : 顶层函数/IP 名称（默认 perf）
# ##################################################################################################

# 默认值
set command "ip"
set device  "xcv80-lsva4737-2MHP-e-S"

# 从环境变量覆盖（若已设置）
if {[info exists ::env(TARGET)]} {
    set command $::env(TARGET)
}
if {[info exists ::env(DEVICE)]} {
    set device $::env(DEVICE)
}
if {[info exists ::env(IPNAME)]} {
    set ipname $::env(IPNAME)
}

set do_sim    0
set do_syn    0
set do_export 0
set do_cosim  0

switch $command {
    "sim"   { set do_sim 1 }
    "syn"   { set do_syn 1 }
    "ip"    { set do_syn 1; set do_export 1 }
    "cosim" { set do_syn 1; set do_cosim 1 }
    "all"   { set do_sim 1; set do_syn 1; set do_export 1; set do_cosim 1 }
    default {
        puts "INFO: Unrecognized command '$command', defaulting to 'ip' flow" 
        set do_syn 1
        set do_export 1
    }
}

open_project -reset build_${ipname}.${device}

add_files src/${ipname}.cpp -cflags "-std=c++14 -Isrc"

if {[string match "slr*" $ipname]} {
    set_top kernel_nlp_${ipname}
} elseif {$ipname == "output"} {
    set_top kernel_nlp
} else {
    set_top $ipname
}

open_solution -reset "sol1"
set_part $device

config_interface -m_axi_addr64=true

# 执行流程
if {$do_sim} {
    csim_design
}

if {$do_syn} {
    create_clock -period 3.33 -name default
    csynth_design
}

if {$do_cosim} {
    cosim_design
}

if {$do_export} {
    # 2025.1 的 config_export 建议放在 export 动作之前
    config_export -format ip_catalog -rtl verilog -display_name "$ipname"
    export_design
}

exit