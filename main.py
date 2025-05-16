#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import os
import re
import sys
import argparse
import chardet
from datetime import datetime

def detect_encoding(file_path):
    """检测文件编码"""
    with open(file_path, 'rb') as f:
        result = chardet.detect(f.read())
    return result['encoding']

def read_file_with_encoding(file_path):
    """尝试多种编码读取文件内容"""
    try:
        # 首先尝试自动检测编码
        encoding = detect_encoding(file_path)
        print(f"检测到文件编码: {encoding}")
        with open(file_path, 'r', encoding=encoding) as f:
            lines = f.readlines()
        return lines
    except Exception as e:
        print(f"使用检测的编码 {encoding} 失败，尝试其他编码...")
        # 如果自动检测失败，尝试多种常见编码
        encodings = ['gbk', 'gb18030', 'cp936', 'utf-8-sig', 'utf-8']
        for enc in encodings:
            try:
                print(f"尝试使用 {enc} 编码...")
                with open(file_path, 'r', encoding=enc) as f:
                    lines = f.readlines()
                print(f"成功使用 {enc} 编码读取文件")
                return lines
            except UnicodeDecodeError:
                continue
        raise Exception("无法识别文件编码，请尝试手动转换文件编码为UTF-8")

def process_alipay_csv(input_content, output_file=None):
    """处理支付宝导出的CSV文件，按照要求格式化
    
    1. 删除前24行
    2. 交易时间列仅保留日期
    3. 排除"不计收支"的行
    4. 排除"交易状态"是"交易关闭"的行
    5. "支出"的金额转为负值，"收入"保持为正值
    6. 输出为CSV格式，逗号分割，双引号包含值
    """
    
    try:
        # 如果输入内容是字符串列表，直接使用；否则假设它是文件路径
        if isinstance(input_content, list):
            lines = input_content
        else:
            lines = read_file_with_encoding(input_content)
        
        # 跳过前24行
        data_lines = lines[24:]
        
        # 使用CSV读取器处理剩余行
        records = []
        reader = csv.reader(data_lines)
        header = next(reader)  # 读取表头
        
        # 尝试找出交易状态列的索引
        transaction_status_index = 3  # 默认假设交易状态是第4列（索引为3）
        
        # 如果表头中有包含"交易状态"的列，则使用该列索引
        for idx, col in enumerate(header):
            if "交易状态" in col:
                transaction_status_index = idx
                print(f"找到交易状态列: {col}，索引为 {idx}")
                break
        
        filtered_count = 0
        closed_count = 0
        non_expense_count = 0
        
        for row in reader:
            # 如果行为空或不含足够列，则跳过
            if not row or len(row) <= max(transaction_status_index, 5, 6):
                continue
            
            # 获取交易时间，仅保留日期
            date_match = re.match(r'(\d{4}-\d{2}-\d{2})', row[0])
            if date_match:
                date = date_match.group(1)
            else:
                continue  # 如果无法解析日期，跳过该行
            
            # 获取收支情况
            income_expense = row[5] if len(row) > 5 else ""
            
            # 跳过"不计收支"的行
            if income_expense == "不计收支":
                non_expense_count += 1
                continue
            
            # 获取交易状态
            transaction_status = row[transaction_status_index] if len(row) > transaction_status_index else ""
            
            # 跳过"交易关闭"的行
            if transaction_status == "交易关闭":
                closed_count += 1
                continue
                
            # 处理金额（支出转为负值）
            amount = row[6] if len(row) > 6 else "0"
            try:
                amount_value = float(amount)
                if income_expense == "支出":
                    amount_value = -amount_value
            except ValueError:
                continue  # 如果金额无法转换为数字，跳过该行
            
            # 保留需要的字段，并替换处理后的值
            new_row = list(row)
            new_row[0] = date  # 替换为仅包含日期的值
            new_row[6] = str(amount_value)  # 替换为处理后的金额
            
            records.append(new_row)
            filtered_count += 1
            
        result = {
            'header': header,
            'records': records,
            'stats': {
                'filtered_count': filtered_count,
                'non_expense_count': non_expense_count,
                'closed_count': closed_count
            }
        }
        
        # 如果指定了输出文件，则写入输出文件
        if output_file:
            # 写入输出文件 - 使用UTF-8编码
            with open(output_file, 'w', encoding='utf-8', newline='') as f:
                writer = csv.writer(f, quoting=csv.QUOTE_ALL)
                writer.writerow(header)  # 写入表头
                writer.writerows(records)  # 写入数据行
            
            print(f"处理完成！已生成文件：{output_file}")
            print(f"共处理 {filtered_count} 条交易记录")
            print(f"过滤掉 {non_expense_count} 条不计收支记录")
            print(f"过滤掉 {closed_count} 条交易关闭记录")
        
        return result
    
    except Exception as e:
        print(f"处理支付宝文件时出错：{e}")
        return None

def process_weixin_csv(input_content, output_file=None):
    """处理微信支付导出的CSV文件，按照要求格式化
    
    1. 删除前16行
    2. 交易时间列仅保留日期
    3. "收/支"列是"支出"，则"金额(元)"是负数，是"收入"则为正数
    4. "当前状态"列过滤排除"已全额退款"，"提现已到账"，"对方已退还"的行
    5. 输出为CSV格式，逗号分割，双引号包含值
    """
    
    try:
        # 如果输入内容是字符串列表，直接使用；否则假设它是文件路径
        if isinstance(input_content, list):
            lines = input_content
        else:
            lines = read_file_with_encoding(input_content)
        
        # 跳过前16行
        data_lines = lines[16:]
        
        # 使用CSV读取器处理剩余行
        records = []
        reader = csv.reader(data_lines)
        header = next(reader)  # 读取表头
        
        # 查找重要列的索引
        time_index = 0       # 交易时间
        type_index = 5       # 收/支
        amount_index = 5     # 金额(元)
        status_index = 7     # 当前状态
        
        # 如果表头中能找到相关列，则使用该列索引
        for idx, col in enumerate(header):
            if "交易时间" in col:
                time_index = idx
                print(f"找到交易时间列: {col}，索引为 {idx}")
            elif "收/支" in col:
                type_index = idx
                print(f"找到收/支列: {col}，索引为 {idx}")
            elif "金额" in col:
                amount_index = idx
                print(f"找到金额列: {col}，索引为 {idx}")
            elif "当前状态" in col:
                status_index = idx
                print(f"找到当前状态列: {col}，索引为 {idx}")
        
        filtered_count = 0
        excluded_status_count = 0
        
        for row in reader:
            # 如果行为空或不含足够列，则跳过
            if not row or len(row) <= max(time_index, type_index, amount_index, status_index):
                continue
            
            # 获取交易时间，仅保留日期
            date_match = re.match(r'(\d{4}-\d{2}-\d{2})', row[time_index])
            if date_match:
                date = date_match.group(1)
            else:
                continue  # 如果无法解析日期，跳过该行
            
            # 获取当前状态
            status = row[status_index] if len(row) > status_index else ""
            
            # 跳过"已全额退款"，"提现已到账"，"对方已退还"的行
            if status in ["已全额退款", "提现已到账", "对方已退还"]:
                excluded_status_count += 1
                continue
            
            # 获取收支情况
            income_expense = row[type_index] if len(row) > type_index else ""
            
            # 处理金额（支出转为负值）
            amount_str = row[amount_index] if len(row) > amount_index else "0"
            # 移除"¥"符号和可能的逗号
            amount_str = amount_str.replace("¥", "").replace(",", "")
            try:
                amount_value = float(amount_str)
                if income_expense == "支出":
                    amount_value = -amount_value
            except ValueError:
                continue  # 如果金额无法转换为数字，跳过该行
            
            # 保留需要的字段，并替换处理后的值
            new_row = list(row)
            new_row[time_index] = date  # 替换为仅包含日期的值
            new_row[amount_index] = str(amount_value)  # 替换为处理后的金额
            
            records.append(new_row)
            filtered_count += 1
        
        result = {
            'header': header,
            'records': records,
            'stats': {
                'filtered_count': filtered_count,
                'excluded_status_count': excluded_status_count
            }
        }
        
        # 如果指定了输出文件，则写入输出文件
        if output_file:
            # 写入输出文件 - 使用UTF-8编码
            with open(output_file, 'w', encoding='utf-8', newline='') as f:
                writer = csv.writer(f, quoting=csv.QUOTE_ALL)
                writer.writerow(header)  # 写入表头
                writer.writerows(records)  # 写入数据行
            
            print(f"处理完成！已生成文件：{output_file}")
            print(f"共处理 {filtered_count} 条交易记录")
            print(f"过滤掉 {excluded_status_count} 条不符合状态的记录")
        
        return result
    
    except Exception as e:
        print(f"处理微信文件时出错：{e}")
        return None

def main():
    # 创建命令行参数解析器
    parser = argparse.ArgumentParser(description='处理支付宝或微信支付导出的CSV文件')
    parser.add_argument('input_file', nargs='?', help='输入文件路径')
    parser.add_argument('-t', '--type', choices=['alipay', 'weixin'], default='alipay', 
                       help='账单类型：alipay（支付宝）或 weixin（微信支付）')
    parser.add_argument('-i', '--input', help='输入文件路径(与位置参数功能相同)')
    parser.add_argument('-o', '--output', help='输出文件路径')
    
    args = parser.parse_args()

    # 处理输入
    input_content = None
    if args.input_file:
        # 优先使用位置参数
        input_file = args.input_file
        print(f"从文件读取：{input_file}")
    elif args.input:
        # 其次使用-i参数
        input_file = args.input
        print(f"从文件读取：{input_file}")
    elif not sys.stdin.isatty():
        # 从标准输入（管道）读取
        print("从标准输入读取内容")
        input_content = sys.stdin.readlines()
    else:
        # 没有提供输入文件
        print("错误：未指定输入文件，请提供文件路径作为参数或使用-i选项")
        print("示例：python main.py 支付宝交易明细.csv")
        print("或者：python main.py -i 支付宝交易明细.csv")
        sys.exit(1)

    # 设置输出文件路径
    if args.output:
        output_file = args.output
    else:
        # 如果没有指定输出文件，根据输入文件名生成输出文件名
        if input_content is None:
            # 使用输入文件路径来生成输出文件名
            dirname = os.path.dirname(os.path.abspath(input_file))
            basename = os.path.basename(input_file)
            if args.type == 'alipay':
                output_basename = f"{os.path.splitext(basename)[0]}_处理后.csv"
            else:
                output_basename = f"{os.path.splitext(basename)[0]}_处理后.csv"
            output_file = os.path.join(dirname, output_basename)
        else:
            # 如果是从标准输入读取，则使用当前目录和默认文件名
            current_dir = os.path.dirname(os.path.abspath(__file__))
            if args.type == 'alipay':
                output_file = os.path.join(current_dir, "支付宝交易明细_处理后.csv")
            else:
                output_file = os.path.join(current_dir, "微信支付账单_处理后.csv")

    # 根据账单类型选择处理函数
    if args.type == 'alipay':
        if input_content is not None:
            process_alipay_csv(input_content, output_file)
        else:
            process_alipay_csv(input_file, output_file)
    else:  # weixin
        if input_content is not None:
            process_weixin_csv(input_content, output_file)
        else:
            process_weixin_csv(input_file, output_file)

if __name__ == "__main__":
    main()