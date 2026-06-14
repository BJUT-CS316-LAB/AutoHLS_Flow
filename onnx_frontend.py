import onnx
from onnx import shape_inference
import numpy as np

class HLSNode:
    def __init__(self, op_type, name, inputs, outputs, attributes=None):
        self.op_type = op_type
        self.name = name
        self.inputs = inputs
        self.outputs = outputs
        self.attributes = attributes or {}
        
        # 对应 AutoHLS_Flow 内部生成的仿射多面体数据
        self.loop_bounds = []     # 例如 [('i', 0, 196), ('j', 0, 768), ('k', 0, 768)]
        self.read_access = []     # 读取的模式
        self.write_access = []    # 写入的模式
        self.computation = ""     # C 代码或 HLS 实例化调用

def get_tensor_shape(value_info):
    """提取 ONNX 节点的形状"""
    shape = []
    for dim in value_info.type.tensor_type.shape.dim:
        if dim.HasField("dim_value"):
            shape.append(dim.dim_value)
        else:
            shape.append(1) # 对于动态 batch_size 默认设为 1
    return shape

def sanitize_name(name):
    # Remove :: and . and _ to avoid conflicts with backend split('_') logic
    clean = name.replace("::", "").replace(".", "").replace("_", "")
    if not clean:
        return "var"
    if clean[0].isdigit():
        clean = "v" + clean
    return clean

def parse_onnx_to_hls(onnx_path="deit_model.onnx"):
    """
    绕过 PoCC，直接将 ONNX 算子映射为 AutoHLS_Flow 语法树/节点列表
    """
    print(f"[ONNX Frontend] Loading model: {onnx_path}")
    try:
        model = onnx.load(onnx_path)
    except FileNotFoundError:
        print(f"[Warning] {onnx_path} not found. Returning a Mock DeiT Attention MatMul node for demonstration.")
        return mock_deit_layer()

    # 推推所有的 shape
    model = shape_inference.infer_shapes(model)
    graph = model.graph

    # 获取所有 Tensor 的 Shape 字典
    tensor_shapes = {}
    
    # 1. Inputs, Value Info, Outputs
    for tensor in list(graph.input) + list(graph.value_info) + list(graph.output):
        tensor_shapes[tensor.name] = get_tensor_shape(tensor)
        
    # 2. Initializers (weights)
    for init in graph.initializer:
        tensor_shapes[init.name] = list(init.dims)

    hls_nodes = []

    # Find all MatMul nodes
    matmul_nodes = [n for n in graph.node if n.op_type == "MatMul"]
    print(f"[ONNX Frontend] Found {len(matmul_nodes)} MatMul nodes in the model.")
    
    if not matmul_nodes:
        print("[Warning] No MatMul nodes found in ONNX. Returning Mock DeiT layer.")
        return mock_deit_layer()

    # We will compile the first 3 MatMul nodes (representing Q, K, V projections in Attention)
    target_nodes = matmul_nodes[:3]
    print(f"[ONNX Frontend] Selected {len(target_nodes)} target nodes for HLS compilation:")
    for t_node in target_nodes:
        print(f"  - {t_node.name}")

    for idx, target_node in enumerate(target_nodes):
        # Sanitize names
        sanitized_inputs = [(sanitize_name(inp), tensor_shapes.get(inp, [])) for inp in target_node.input]
        sanitized_outputs = [(sanitize_name(out), tensor_shapes.get(out, [])) for out in target_node.output]

        p_node = HLSNode(
            op_type=target_node.op_type,
            name=sanitize_name(target_node.name),
            inputs=sanitized_inputs,
            outputs=sanitized_outputs,
        )

        # Perform fallback shape inference for MatMul
        shape_A = sanitized_inputs[0][1]
        shape_B = sanitized_inputs[1][1]

        # Defaults for DeiT
        M, N, K = 197, 768, 768

        if shape_B and len(shape_B) >= 2:
            K = shape_B[-2]
            N = shape_B[-1]
        elif shape_A and len(shape_A) >= 2:
            M = shape_A[-2]
            K = shape_A[-1]

        # Ensure inputs and outputs have the resolved static shapes
        p_node.inputs[0] = (sanitized_inputs[0][0], [M, K])
        p_node.inputs[1] = (sanitized_inputs[1][0], [K, N])
        p_node.outputs[0] = (sanitized_outputs[0][0], [M, N])

        p_node.loop_bounds = [
            ('i', 0, M),
            ('j', 0, N),
            ('k', 0, K)
        ]
        
        input_0_name = sanitized_inputs[0][0]
        input_1_name = sanitized_inputs[1][0]
        output_name = sanitized_outputs[0][0]

        p_node.read_access = [
            f"{input_0_name}[i][k]",
            f"{input_1_name}[k][j]"
        ]
        p_node.write_access = [
            f"{output_name}[i][j]"
        ]
        p_node.computation = f"{output_name}[i][j] += {input_0_name}[i][k] * {input_1_name}[k][j];"

        hls_nodes.append(p_node)

    return hls_nodes

def mock_deit_layer():
    """没有真实 ONNX 文件时的 Mock 数据：DeiT 的注意力查询降维操作"""
    # X: [197, 768] (Seq_len=197, Dim=768) 
    # Wq: [768, 768]
    node = HLSNode("MatMul", "Attention_Q_Proj", 
                          inputs=[("X", [197, 768]), ("Wq", [768, 768])], 
                          outputs=[("Q", [197, 768])])
    node.loop_bounds = [('i', 0, 197), ('j', 0, 768), ('k', 0, 768)]
    node.read_access = ["X[i][k]", "Wq[k][j]"]
    node.write_access = ["Q[i][j]"]
    node.computation = "Q[i][j] += X[i][k] * Wq[k][j];"
    return [node]

if __name__ == "__main__":
    import sys
    onnx_path = sys.argv[1] if len(sys.argv) > 1 else "dummy_deit.onnx"
    nodes = parse_onnx_to_hls(onnx_path)
    
    print("-" * 50)
    # Only print nodes that actually have loop bounds to avoid printing 1000 empty nodes
    active_nodes = [n for n in nodes if n.loop_bounds]
    print(f"Total active nodes: {len(active_nodes)}")
    for n in active_nodes[:5]: # Print first 5 active nodes
        print(f"Op: {n.op_type} | Name: {n.name}")
        print(f"  Inputs : {n.inputs}")
        print(f"  Outputs: {n.outputs}")
        if n.loop_bounds:
            print("  [Generated AutoHLS_Flow Loops]")
            for lb in n.loop_bounds:
                print(f"    for(int {lb[0]} = {lb[1]}; {lb[0]} < {lb[2]}; {lb[0]}++)")
            print(f"        {n.computation}")
    print("-" * 50)
