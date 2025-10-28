import json
import subprocess
import sys
import time
import os
import re
from typing import Dict, List, Any

IGNORE_SERVICE_NAMES = [
    'describe_parameters',
    'get_parameter_types',
    'get_parameters',
    'list_parameters',
    'set_parameters',
    'set_parameters_atomically',
]

IGNORE_TOPIC_NAMES = [
    'parameter_events',
]


def run_ros2_command(cmd_list: List[str]) -> str | None:
    """
    ROS 2のCLIコマンドを実行し、標準出力を取得するヘルパー関数。
    """
    try:
        env = os.environ.copy()
        result = subprocess.run(
            cmd_list,
            check=True,
            capture_output=True,
            text=True,
            env=env,
            timeout=10
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        if "Node not found" not in e.stderr:
            print(f"Error running ROS 2 command: {' '.join(cmd_list)}", file=sys.stderr)
            print(f"Stderr: {e.stderr}", file=sys.stderr)
        return None
    except FileNotFoundError:
        print(f"ROS 2 command not found. Ensure ROS 2 environment is sourced.", file=sys.stderr)
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print(f"ROS 2 command timed out: {' '.join(cmd_list)}", file=sys.stderr)
        return None

def parse_param_get_output(output: str) -> Dict[str, Any]:
    """
    'ros2 param get' の出力をパースし、型と値を抽出する。
    """
    param = {"value": None, "type": "unknown"}

    # 1. Pythonスタイルの出力 (型と値が一括で出ている形式) をチェック
    match_python = re.search(r'(String|Integer|Boolean|Double)\s+value\s+is:\s+(.*)', output, re.DOTALL | re.IGNORECASE)
    if match_python:
        value_type = match_python.group(1).lower()
        value_str = match_python.group(2).strip()

        param["type"] = value_type
        if value_type == 'integer':
            try: param["value"] = int(value_str)
            except ValueError: param["value"] = value_str
        elif value_type == 'double':
            try: param["value"] = float(value_str)
            except ValueError: param["value"] = value_str
        elif value_type == 'boolean':
            param["value"] = value_str.lower() == 'true'
        else:
            param["value"] = value_str
        return param

    # 2. 一般的な Type: / Value: の行をチェック
    type_match = re.search(r'Type:\s+(\w+)', output, re.IGNORECASE)
    value_match = re.search(r'Value:\s+(.*)', output, re.DOTALL)

    if type_match:
        param["type"] = type_match.group(1).lower()

    if value_match:
        value_str = value_match.group(1).strip()
        param["value"] = value_str

    return param

def parse_interface_schema(interface_type: str) -> List[str]:
    """
    'ros2 interface show' コマンドを実行し、出力を行ごとにパースしてリストで返す。
    """
    output = run_ros2_command(["ros2", "interface", "show", interface_type])
    schema: List[str] = []

    if output:
        for line in output.split('\n'):
            line = line.rstrip()
            trimmed_line_start = line.lstrip()

            if not trimmed_line_start or trimmed_line_start.startswith('#'):
                continue

            schema.append(line)

    return schema


def collect_ros2_graph_data() -> Dict[str, Any]:
    """
    ROS 2のノード、トピック、サービス情報をCLI経由で収集し、JSON構造を構築する。
    """

    # 時間計測の開始
    start_time = time.time()

    graph_data: Dict[str, Any] = {
        "graph_metadata": {
            "created_at": int(time.time() * 1000),
            "description": "Captured ROS 2 network graph using subprocess"
        },
        "nodes": {},
        "topics": {},
        "services": {},
        "actions": {},
        "connections": []
    }

    node_name_to_id: Dict[str, str] = {}

    # 1. ノードリストの取得と総数カウント
    node_list_raw = run_ros2_command(["ros2", "node", "list", "-a"])
    node_list_all = [n.strip() for n in (node_list_raw.split('\n') if node_list_raw else []) if n.strip()]

    node_list_filtered = []
    for n in node_list_all:
        if not n.startswith('/_ros2cli_') and n != '/ros2_state_yaml_dumper_node':
            node_list_filtered.append(n)

    total_nodes = len(node_list_filtered)
    node_idx = 0

    # 2. トピックとサービスのリストを事前に取得 (接続情報構築のため)
    topic_list_raw = run_ros2_command(["ros2", "topic", "list", "-t"])
    service_list_raw = run_ros2_command(["ros2", "service", "list", "-t"])

    discovered_topics: Dict[str, str] = {} # name -> type
    discovered_services: Dict[str, str] = {} # name -> type

    if topic_list_raw:
        for line in topic_list_raw.split('\n'):
            match = re.match(r'(/[\w/]+)\s+\[([\w/]+)\]', line.strip())
            if match:
                name = match.group(1)
                last_topic_name = name.split('/')[-1]
                if not last_topic_name in IGNORE_TOPIC_NAMES:
                    type_name = match.group(2)
                    discovered_topics[name] = type_name

    if service_list_raw:
        for line in service_list_raw.split('\n'):
            match = re.match(r'(/[\w/]+)\s+\[([\w/]+)\]', line.strip())
            if match:
                name = match.group(1)
                last_service_name = name.split('/')[-1]
                if not last_service_name in IGNORE_SERVICE_NAMES:
                    type_name = match.group(2)
                    discovered_services[name] = type_name

    # 3. ノードごとの情報と接続の収集
    for i, node_name in enumerate(node_list_filtered):
        # ★ 修正2: 進捗情報の出力
        processed_nodes = i + 1
        progress = (processed_nodes / total_nodes) * 100
        print(f"Processing node {processed_nodes}/{total_nodes} ({progress:.0f}%): {node_name}", file=sys.stderr)

        node_id = f"node_{node_idx}"
        node_idx += 1
        node_name_to_id[node_name] = node_id

        # パス構築
        path_parts = [p for p in node_name.split('/') if p]

        # パラメータの取得
        parameters: List[Dict[str, Any]] = []
        param_list_raw = run_ros2_command(["ros2", "param", "list", node_name, "--include-hidden"])

        if param_list_raw:
            for param_name_line in param_list_raw.split('\n'):
                param_name_line = param_name_line.strip()
                if not param_name_line or param_name_line.endswith(':'):
                    continue

                param_name = param_name_line.split(':')[0].strip()

                param_get_raw = run_ros2_command(["ros2", "param", "get", node_name, param_name])

                if param_get_raw:
                    parsed_param = parse_param_get_output(param_get_raw)
                    # 値を TypeScript スキーマに合わせて文字列に変換 (Noneでないことを確認)
                    param_value_str = str(parsed_param["value"]) if parsed_param["value"] is not None else "None"

                    parameters.append({
                        "name": param_name,
                        "value": param_value_str,
                        "type": parsed_param["type"]
                    })

        # ノード情報の構築
        graph_data["nodes"][node_name] = {
            "id": node_id,
            "name": node_name,
            "path": path_parts,
            "type": "component",
            "parameters": parameters
        }

        # 接続情報の収集
        node_info_raw = run_ros2_command(["ros2", "node", "info", node_name])
        if node_info_raw:
            current_section = None
            for line in node_info_raw.split('\n'):
                line = line.strip()
                if line.endswith(':'):
                    current_section = line[:-1]
                    continue
                if not current_section or not line:
                    continue

                name = line.split(':')[0].strip() # トピック/サービス名

                if current_section == 'Publishers' and name in discovered_topics:
                    graph_data["connections"].append({
                        "type": "topic",
                        "source_id": node_name,
                        "target_id": name,
                        "direction": "publish"
                    })
                elif current_section == 'Subscribers' and name in discovered_topics:
                    graph_data["connections"].append({
                        "type": "topic",
                        "source_id": name,
                        "target_id": node_name,
                        "direction": "subscribe"
                    })
                elif current_section == 'Service Servers' and name in discovered_services:
                    graph_data["connections"].append({
                        "type": "service",
                        "source_id": name,
                        "target_id": node_name,
                        "direction": "provide"
                    })
                elif current_section == 'Service Clients' and name in discovered_services:
                    graph_data["connections"].append({
                        "type": "service",
                        "source_id": node_name,
                        "target_id": name,
                        "direction": "call"
                    })

    # 4. トピック情報の構築 (メッセージスキーマの取得)
    for name, type_name in discovered_topics.items():
        graph_data["topics"][name] = {
            "id": name,
            "name": name,
            "type": type_name,
            "message_schema": parse_interface_schema(type_name)
        }

    # 5. サービス情報の構築 (メッセージスキーマの取得)
    for name, type_name in discovered_services.items():
        graph_data["services"][name] = {
            "id": name,
            "name": name,
            "type": type_name,
            "message_schema": parse_interface_schema(type_name)
        }

    # ★ 修正1: 処理終了時間の計測と実行時間の計算
    end_time = time.time()
    duration = end_time - start_time
    print(f"Total execution time (collect_ros2_graph_data): {duration:.3f} seconds", file=sys.stderr)

    return graph_data

def main():
    """
    メイン実行関数。グラフデータを収集し、JSONファイルに保存する。
    """
    if 'AMENT_PREFIX_PATH' not in os.environ:
        print("Warning: ROS 2 environment does not appear to be sourced. Command execution may fail.", file=sys.stderr)

    graph_data = collect_ros2_graph_data()

    # 出力をJSON形式に変更
    file_path = "ros2_graph_dump.json"
    try:
        with open(file_path, "w") as f:
            json.dump(graph_data, f, indent=2)
        print(f"Successfully dumped ROS 2 graph data to {file_path}")
    except IOError as e:
        print(f"Error saving JSON file: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()