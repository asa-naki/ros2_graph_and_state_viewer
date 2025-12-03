#!/usr/bin/env python3
"""
ROS2パラメータ取得方法の速度比較テスト

方法1: ros2 param list + ros2 param get (各パラメータごと)
方法2: ros2 param dump (一括取得)
"""

import subprocess
import time
import yaml
import sys
import os


def run_ros2_command(cmd_list):
    """ROS2コマンドを実行"""
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
        print(f"Error: {e.stderr}", file=sys.stderr)
        return None
    except subprocess.TimeoutExpired:
        print(f"Command timed out: {' '.join(cmd_list)}", file=sys.stderr)
        return None


def method1_param_list_get(node_name):
    """
    方法1: ros2 param list で一覧を取得し、各パラメータをros2 param getで取得
    """
    parameters = {}
    
    # パラメータリストを取得
    param_list_raw = run_ros2_command(["ros2", "param", "list", node_name, "--include-hidden"])
    
    if param_list_raw:
        for param_name_line in param_list_raw.split('\n'):
            param_name_line = param_name_line.strip()
            if not param_name_line or param_name_line.endswith(':'):
                continue
            
            param_name = param_name_line.split(':')[0].strip()
            
            # 各パラメータの値を取得
            param_get_raw = run_ros2_command(["ros2", "param", "get", node_name, param_name])
            
            if param_get_raw:
                parameters[param_name] = param_get_raw
    
    return parameters


def method2_param_dump(node_name):
    """
    方法2: ros2 param dump で一括取得
    """
    parameters = {}
    
    # パラメータを一括ダンプ (--include-hiddenオプションを追加)
    dump_output = run_ros2_command(["ros2", "param", "dump", node_name, "--include-hidden"])
    
    if dump_output:
        try:
            # YAMLをパース
            yaml_data = yaml.safe_load(dump_output)
            if yaml_data and node_name in yaml_data:
                ros_params = yaml_data[node_name].get('ros__parameters', {})
                parameters = ros_params
        except yaml.YAMLError as e:
            print(f"YAML parse error: {e}", file=sys.stderr)
    
    return parameters


def main():
    # ノードリストを取得
    node_list_raw = run_ros2_command(["ros2", "node", "list"])
    if not node_list_raw:
        print("No nodes found. Make sure ROS2 nodes are running.", file=sys.stderr)
        sys.exit(1)
    
    node_list = [n.strip() for n in node_list_raw.split('\n') if n.strip()]
    
    # _ros2cliなどの内部ノードを除外
    node_list_filtered = [n for n in node_list 
                          if not n.startswith('/_ros2cli_') 
                          and n != '/ros2_state_yaml_dumper_node']
    
    if not node_list_filtered:
        print("No valid nodes found for testing.", file=sys.stderr)
        sys.exit(1)
    
    print("=" * 60)
    print("ROS2 Parameter Retrieval Speed Comparison Test")
    print("=" * 60)
    print(f"\nFound {len(node_list_filtered)} nodes to test\n")
    
    total_time_method1 = 0
    total_time_method2 = 0
    total_params_method1 = 0
    total_params_method2 = 0
    
    for node_name in node_list_filtered:
        print(f"\nTesting node: {node_name}")
        print("-" * 60)
        
        # 方法1: param list + param get
        start_time = time.time()
        params1 = method1_param_list_get(node_name)
        time_method1 = time.time() - start_time
        
        # 方法2: param dump
        start_time = time.time()
        params2 = method2_param_dump(node_name)
        time_method2 = time.time() - start_time
        
        num_params1 = len(params1)
        num_params2 = len(params2)
        
        total_time_method1 += time_method1
        total_time_method2 += time_method2
        total_params_method1 += num_params1
        total_params_method2 += num_params2
        
        print(f"Method 1 (param list + get): {time_method1:.3f}s - {num_params1} parameters")
        print(f"Method 2 (param dump):       {time_method2:.3f}s - {num_params2} parameters")
        
        # パラメータ数が異なる場合、差分を表示
        if num_params1 != num_params2:
            print(f"⚠️  Parameter count mismatch!")
            params1_set = set(params1.keys())
            params2_set = set(params2.keys())
            
            only_in_method1 = params1_set - params2_set
            only_in_method2 = params2_set - params1_set
            
            if only_in_method1:
                print(f"   Only in Method 1: {sorted(only_in_method1)}")
            if only_in_method2:
                print(f"   Only in Method 2: {sorted(only_in_method2)}")
        
        if time_method1 > 0 and time_method2 > 0:
            speedup = time_method1 / time_method2
            if speedup > 1:
                print(f"→ Method 2 is {speedup:.2f}x faster")
            else:
                print(f"→ Method 1 is {1/speedup:.2f}x faster")
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total nodes tested: {len(node_list_filtered)}")
    print(f"\nMethod 1 (param list + get):")
    print(f"  Total time: {total_time_method1:.3f}s")
    print(f"  Total parameters: {total_params_method1}")
    print(f"  Avg time per node: {total_time_method1/len(node_list_filtered):.3f}s")
    
    print(f"\nMethod 2 (param dump):")
    print(f"  Total time: {total_time_method2:.3f}s")
    print(f"  Total parameters: {total_params_method2}")
    print(f"  Avg time per node: {total_time_method2/len(node_list_filtered):.3f}s")
    
    if total_time_method1 > 0 and total_time_method2 > 0:
        speedup = total_time_method1 / total_time_method2
        print(f"\n{'='*60}")
        if speedup > 1:
            print(f"Method 2 (param dump) is {speedup:.2f}x FASTER overall")
        else:
            print(f"Method 1 (param list + get) is {1/speedup:.2f}x FASTER overall")
        print(f"{'='*60}")


if __name__ == "__main__":
    main()
