import json
import ast

def fix_json_format(file_path):
    """
    读取包含Python字典的文件并将其转换为正确的JSON格式
    """
    try:
        # 读取文件内容
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 使用ast.literal_eval安全地解析Python字典
        # 这比eval更安全，因为它只评估字面量表达式
        data = ast.literal_eval(content)
        
        # 将数据写入为正确格式的JSON
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"成功修复 {file_path} 文件的JSON格式")
        return True
        
    except Exception as e:
        print(f"修复过程中出现错误: {str(e)}")
        return False

if __name__ == "__main__":
    # 修复test.json文件
    success = fix_json_format('roo-code-body.json')
    
    if success:
        print("JSON格式修复完成！")
    else:
        print("修复失败，请检查文件内容")