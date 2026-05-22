  pip install paramiko

  使用方式：
  python3 gpu_monitor.py                           # 打印 + 自动保存 all_gpu_info.json
  python3 gpu_monitor.py --save result.json        # 指定输出文件
  python3 gpu_monitor.py --no-local                # 跳过本机，只查远程
  python3 gpu_monitor.py --config custom.json      # 指定其他配置文件

