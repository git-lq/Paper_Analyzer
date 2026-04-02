import os
import json
import time
import shutil
import requests
from google import genai
import uuid # 这是一个内置库，不用额外安装，用来生成随机纯英文文件名
import urllib.parse
import datetime
import hashlib
from dotenv import load_dotenv

# ====================================================
# 🔴 【读取 keys and paths】 🔴
# ====================================================
#region
load_dotenv()
# 读取 keys
GEMINI_API_KEY_EMP = os.getenv("GEMINI_API_KEY_EMP")
GEMINI_API_KEY_REV = os.getenv("GEMINI_API_KEY_REV")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID_EMP = os.getenv("DATABASE_ID_EMP")
DATABASE_ID_REV = os.getenv("DATABASE_ID_REV")
EASYSCHOLAR_KEY = os.getenv("EASYSCHOLAR_KEY")

# 文件夹路径
INPUT_FOLDER_EMP = os.getenv("INPUT_FOLDER_EMP")
PROCESSED_FOLDER_EMP = os.getenv("PROCESSED_FOLDER_EMP")
INPUT_FOLDER_REV = os.getenv("INPUT_FOLDER_REV")
PROCESSED_FOLDER_REV = os.getenv("PROCESSED_FOLDER_REV")
BIBTEX_FOLDER = os.getenv("BIBTEX_FOLDER") # 本地 Bibtex 备份目录
OBSIDIAN_VAULT = os.getenv("OBSIDIAN_VAULT") # Obsidian Vault 名称
OBSIDIAN_FOLDER = os.getenv("OBSIDIAN_FOLDER") # 本地 Markdown 备份目录
HASH_DB_FILE_EMP = os.getenv("HASH_DB_FILE_EMP") # 文件指纹库路径
HASH_DB_FILE_REV = os.getenv("HASH_DB_FILE_REV") # 文件指纹库路径
# ==========================================

# 推荐使用的模型名称（请确保你在 Google AI Studio 中看到的名字与此一致）
MODEL_NAME = os.getenv("MODEL_NAME")

# 读取 Master Prompt
from prompts import PROMPT_EMP, PROMPT_REV
#endregion

# ==========================================
# 🟢 核心逻辑区 (使用全新 google.genai 架构) 🟢
# ==========================================


# 提示用户选择文献类型，并获取输入
def get_user_input():
    choice = ""
    literature_type = ""
    while choice == "":
        print("=============================")
        print("😊 Hello! I'm Paper Analyzer.")
        print("=============================")
        print("\nPlease select the literature type you want analyzed:")
        print("1. Empirical research papers\n2. Review articles")

        choice = input("Enter the number of your choice: ").strip()

        if choice == "1":
            literature_type = "Empirical"
            print(f"\nI'm going to analyze {literature_type} papers.")
            print("⚠️ Please make sure the PDF files in your INPUT FOLDER correspond to this type ⚠️")
            confirm = input("Do you confirm? Yes(y)/No(n): ").strip()
            if confirm == "y":
                break
            else:
                print("Please choose the literature type again, or press CTRL+C to break the program.\n")
                choice = ""
                literature_type = ""
                continue
        elif choice == "2":
            literature_type = "Review"
            print(f"\nI'm going to analyze {literature_type} papers.")
            print("⚠️ Please make sure the PDF files in your INPUT FOlDER correspond to this type ⚠️")
            confirm = input("Do you confirm?  Yes(y)/No(n): ").strip()
            if confirm == "y":
                break
            else:
                print("Please choose the literature type again, or press CTRL+C to break the program.\n")
                choice = ""
                literature_type = ""
                continue
        else:
            print("❌Invalid choice. Please enter 1 or 2.\n")
            choice = ""
            continue
    
    return literature_type


# region 哈希值查重、生成记录
# 计算文件 MD5 哈希值
def get_file_md5(file_path):
    """计算文件的 MD5 唯一指纹"""
    hasher = hashlib.md5()
    with open(file_path, 'rb') as f:
        # 分块读取，防止 PDF 太大撑爆内存
        for chunk in iter(lambda: f.read(4096), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

# 根据 MD5 哈希值，在指纹库里检查是否重复
def is_duplicate(file_hash, HASH_DB_FILE):
    """去指纹库里查重"""
    if not os.path.exists(HASH_DB_FILE):
        return False
    with open(HASH_DB_FILE, 'r', encoding='utf-8') as f:
        hashes = f.read().splitlines()
    return file_hash in hashes

# 将 MD5 哈希值写入指纹库
def record_hash(file_hash, HASH_DB_FILE):
    """解析成功后，将指纹刻入历史记录碑"""
    print("7️⃣ 正在记录哈希值指纹...")
    with open(HASH_DB_FILE, 'a', encoding='utf-8') as f:
        f.write(file_hash + '\n')
    
    print("   ✅ 哈希值记录成功!")
# endregion

# 智能调整所有标签类属性的文字大小写，避免大写标签和小写标签重复生成
def smart_format(text):
        if not text:
            return ""
        words = str(text).strip().split()
        formatted_words = []
        for word in words:
            # 1. 如果是全大写缩写（如 GIS），原样保留
            if word.isupper():
                formatted_words.append(word)
            # 2. 否则，仅首字母大写，后续字母维持原样（保护 ArcGIS 等专有名词）
            else:
                formatted_words.append(word[0].upper() + word[1:])
        return " ".join(formatted_words)

# region 第1步：上传文件到 AI 并获取 JSON
def get_paper_analysis(prompt, pdf_path, client):
    print(f"1️⃣ 正在上传文件并调用大模型分析...")
    uploaded_file = None
    
    # 【核心修复】：生成一个绝对不会包含中文的临时文件名
    temp_pdf_path = f"temp_upload_{uuid.uuid4().hex}.pdf"
    
    try:
        # 将原始带中文名的文件，复制一份为纯英文临时文件
        shutil.copy2(pdf_path, temp_pdf_path)
        
        # 1. 上传这个纯英文的临时文件
        uploaded_file = client.files.upload(file=temp_pdf_path)
        print("   ✅ 文件上传成功，等待 AI 分析...")
        
        # 2. 调用模型生成内容
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=[prompt, uploaded_file]
        )
        
        # 3. 清洗并解析 JSON
        raw_text = response.text.strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]

        print("   ✅ 成功获取返回 JSON 并开始解析!")    
        return json.loads(raw_text.strip())
        
    except Exception as e:
        print(f"   ❌ 解析失败: {e}")
        return None
    finally:
        # 4. 善后处理：删除本地生成的那个临时文件（擦除痕迹）
        if os.path.exists(temp_pdf_path):
            os.remove(temp_pdf_path)
            
        # 5. 删除云端文件以释放空间
        if uploaded_file:
            try:
                client.files.delete(name=uploaded_file.name)
            except:
                pass

# region 第2步：查询期刊等级
def get_journal_ranks(journal_name):
    """
    调用 EasyScholar API 获取期刊等级，并返回格式化后的列表
    """
    print(f"2️⃣ 正在查询期刊 {journal_name} 等级...")

    rank_results = []
    indicator_dict = {
        "sciif": 0,
        "sciif5": 0,
        "jci": 0
    }

    if not journal_name or journal_name == "N/A":
        rank_results = ["N/A"]
        print("   ⏩ 非期刊文章，跳过该步骤！")
        return rank_results, indicator_dict

    url = "https://www.easyscholar.cc/open/getPublicationRank"
    
    # 构造请求参数，requests 库会自动处理类似 encodeURIComponent 的 url 编码
    params = {
        "secretKey": EASYSCHOLAR_KEY,
        "publicationName": journal_name
    }
    
    # 字典白名单：从官方返回的37个字段中，只提取我们最关心的硬核指标
    # 左边是 API 返回的字段名，右边是你想在 Obsidian/Notion 里显示的名字
    target_ranks = {
        "sci": "SCI",
        "ssci": "SSCI",
        "ahci": "A&HCI",
        "cssci": "CSSCI",
        "sciBase": "中科基",
        "sciUp": "中科升",
        "pku": "北大核",
        "sciwarn": "中科院预警",
        "zhongguokejihexin": "中国科技核心期刊",
        "ccf": "CCF",
        "eii": "EI",
    }
    target_ranks_custom = {
        "1635615726460694528": "Scopus",
        "1704511887208226816": "ESCI",
        "1909811574273142784": "CSCD",
        "2013126792423587840": "CSSCI扩"
    }
    
    custom_rank_fieldsname = ["abbName", "oneRankText", "twoRankText", "threeRankText", "fourRankText", "fiveRankText"]

    try:
        # 遵守官方限速：每秒最多2次请求
        time.sleep(1) 
        
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        # 检查是否成功
        if data.get("code") == 200 and data.get("data"):
            # 获取官方数据集中的所有等级信息
            official_ranks = data["data"].get("officialRank", {}).get("all", {})
            custom_ranks = data["data"].get("customRank", {}).get("rank", [])
            custom_rank_dicts = data["data"].get("customRank", {}).get("rankInfo", [])
            
            if official_ranks != None:
                # 获取影响因子
                for indicator in indicator_dict:
                    if indicator in official_ranks:
                        indicator_dict[indicator] = round(float(official_ranks[indicator]),2)

                # 遍历官方排名白名单，如果期刊在这个榜单上有排名，就提取出来
                for key, display_name in target_ranks.items():
                    if key in official_ranks:
                        rank_value = official_ranks[key]
                        if rank_value == display_name:
                            rank_results.append(f"{display_name}")
                        else:
                            rank_results.append(f"{display_name} {rank_value}")
                
                # 遍历自定义排名白名单，如果期刊在这个榜单上有排名，就提取出来
                for custom_rank in custom_ranks:
                    custom_rank_id, custom_rank_num = custom_rank.split("&&&")
                    for custom_rank_dict in custom_rank_dicts:
                        if custom_rank_dict.get("uuid") == custom_rank_id:
                            custom_rank_num = int(custom_rank_num)
                            custom_rank_value = custom_rank_dict[custom_rank_fieldsname[custom_rank_num]]
                            display_name = target_ranks_custom[custom_rank_id]
                            if custom_rank_value == " ":
                                rank_results.append(f"{display_name}")
                            else:
                                rank_results.append(f"{display_name} {custom_rank_value}")
                print("   ✅ 成功获取期刊等级并记录!")
                return rank_results, indicator_dict
            else:
                print("   ⚠️ 期刊不存在或名称错误，请检查后自行查询等级和因子，并填入Obsidian和Notion！")
                return ["N/A"], indicator_dict
                                
    except Exception as e:
        if rank_results:
            print(f"   ⚠️ 仅获取部分期刊等级，错误: {e}")
            return rank_results, indicator_dict
        else:
            print(f"   ⚠️ 未能获取期刊等级，错误: {e}，请自行查询等级和因子，并填入Obsidian和Notion！")
            return ["N/A"], indicator_dict
        

# region 第3步：输出为 .md 文件，保存在 Obsidian
def save_to_obsidian(data, pdf_local_path, journal_ranks, indicators, literature_type):
    print("3️⃣ 正在保存本地 .md 文件及 entities 文件到 Obsidian...")
    if not os.path.exists(OBSIDIAN_FOLDER):
        os.makedirs(OBSIDIAN_FOLDER)
    
    # 检查并创建一个 Entities 文件夹来存放作者、方法等“实体节点”
    entities_folder = os.path.join(OBSIDIAN_FOLDER, "Entities")
    if not os.path.exists(entities_folder):
        os.makedirs(entities_folder)

    props = data.get("properties", {})
    md_content = data.get("markdown_content", "无内容")

    # 定义函数生成批量生成空白的实体文件（为图谱上色做准备）
    def create_entity(prefix, items, subfolder_name):
        # 确保某类实体的专属子文件夹存在
        subfolder_path = os.path.join(entities_folder, subfolder_name)
        if not os.path.exists(subfolder_path):
            os.makedirs(subfolder_path)

        if not isinstance(items, list):
            items = [items]
        
        for item in items:
            clean_name = smart_format(item)
            if not clean_name: continue
            # 剔除不能作为文件名的特殊字符
            safe_name = clean_name
            for char in ['<', '>', ':', '"', '/', '\\', '|', '?', '*']:
                safe_name = safe_name.replace(char, '_')
            
            # 生成诸如 "👤 Batty, Michael.md" 的空文件
            entity_filename = f"{prefix} {safe_name}.md"
            entity_filepath = os.path.join(subfolder_path, entity_filename)
            
            # 如果不存在才创建，避免重复覆盖
            if not os.path.exists(entity_filepath):
                with open(entity_filepath, 'w', encoding='utf-8') as f:
                    f.write(f"---\ntags: [{prefix}]\n---\n") # 顺手加个标签属性

    # 生成安全的文件名（使用中文短标题+第一作者，去掉特殊字符）
    safe_title = str(props.get("Title Short CN", "Untitled_Paper"))
    first_author = str(props.get("Authors", [])[0])
    invalid_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
    for char in invalid_chars:
        safe_title = safe_title.replace(char, '_')

    # 检查并创建 Empirical 或 Review 文件夹，创建目标文件名
    if literature_type == "Empirical":
        type_folder = os.path.join(OBSIDIAN_FOLDER, "Empirical")
    elif literature_type == "Review":
        type_folder = os.path.join(OBSIDIAN_FOLDER, "Review")
    if not os.path.exists(type_folder):
            os.makedirs(type_folder)
    filepath = os.path.join(type_folder, f"{safe_title} - {first_author}.md")
    
    # 生成 Obsidian 专属的本地文件安全链接 (file:///)
    abs_path = os.path.abspath(pdf_local_path).replace("\\", "/")
    # 必须对路径进行 URL 编码，否则路径里的空格会导致链接断裂
    encoded_path = urllib.parse.quote(abs_path) 
    obsidian_file_link = f"file:///{encoded_path}"

    # 生成 DOI 链接
    doi = props.get("DOI", "N/A")
    doi_link = f"https://doi.org/{doi}" if doi != "N/A" else "N/A"

    # 处理 journal_ranks 并生成 YAML
    if journal_ranks[0] != "N/A":
        journal_ranks_yaml = "\n".join([f"  - \"[[🎖️ {rank}]]\"" for rank in journal_ranks])
    else:
        journal_ranks_yaml = '  - "N/A"'

    #region 这里是使用双向链接记录元数据，该方法已废弃，保持注释状态即可
    # # 2. 自动生成 Obsidian 双向链接 [[ ]]
    # authors = ", ".join([f"[[{str(a).strip()}]]" for a in props.get("Authors", [])])
    # data_tags = ", ".join([f"[[{str(t).strip()}]]" for t in props.get("Data Tags", [])])
    # method_tags = ", ".join([f"[[{str(t).strip()}]]" for t in props.get("Method Tags", [])])
    # context_tags = ", ".join([f"[[{str(t).strip()}]]" for t in props.get("Context Tags", [])])
    # keywords = ", ".join([f"[[{str(t).strip()}]]" for t in props.get("Keywords", [])])
    # logic_type = f"[[Type {props.get('Logic Type', 'G')}]]"
    # year = f"[[{props.get('Year', 'Unknown')}]]"

#     # 3. 拼装完美的 Obsidian 笔记结构
#     obsidian_note = f"""# {props.get('Title', 'Untitled')}

# > [!info] 📄 **元数据速览**
# > - **中英简评:** {props.get('Short Title (EN)', '')} | {props.get('短标题 (中文)', '')}
# > - **年份:** {year}
# > - **作者:** {authors}
# > - **逻辑类型:** {logic_type}
# > - **关键词:** {keywords}
# > - **数据标签:** {data_tags}
# > - **方法标签:** {method_tags}
# > - **上下文标签:** {context_tags}
# > - **综合评价:** 相关度 {props.get('Relevance', '')} | 难度 {props.get('Difficulty', '')} | 推荐度 {props.get('Overall', '')}
# > - **DOI / Link:** {props.get('DOI', 'N/A')}

# ---
# {md_content}
# """
    #endregion

    # 生成带特殊前缀的 YAML 列表项 (防错处理：加双引号防转义)
    authors_yaml = "\n".join([f"  - \"[[👤 {str(a).strip()}]]\"" for a in props.get("Authors", [])])
    methods_yaml = "\n".join([f"  - \"[[🛠️ {str(t).strip()}]]\"" for t in props.get("Method Tags", [])])
    data_yaml = "\n".join([f"  - \"[[📊 {str(d).strip()}]]\"" for d in props.get("Data Tags", [])])
    context_yaml = "\n".join([f"  - \"[[🗺️ {str(s).strip()}]]\"" for s in props.get("Context Tags", [])])
    keywords_yaml = "\n".join([f"  - \"[[🔑 {str(p).strip()}]]\"" for p in props.get("Keywords", [])])
    # 以下是独属Review类文章的几个属性
    if literature_type == "Review":
        fields_yaml = "\n".join([f"  - \"[[🌐 {smart_format(p)}]]\"" for p in props.get("Fields", [])])
        lit_src_yaml = "\n".join([f"  - \"[[📚 {smart_format(r)}]]\"" for r in props.get("Lit Src Tags", [])])
        filter_yaml = "\n".join([f"  - \"[[🔍 {smart_format(b)}]]\"" for b in props.get("Filter Tags", [])])

    # 拼装标准的 YAML Frontmatter 属性 + 正文
    # 实证文章
    if literature_type == "Empirical":
        obsidian_note = f"""---
Title: "{props.get('Title Full', 'Untitled')}"
Aliases: ["{props.get('Title Short EN', '')}", "{props.get('Title Short CN', '')}"]
Year: {props.get('Year', 'Unknown')}
Authors:
{authors_yaml if authors_yaml else '  - "N/A"'}
Journal: "[[📓 {props.get('Journal', 'N/A')}]]"
J_ranks:
{journal_ranks_yaml}
J_IF: {indicators['sciif'] if indicators["sciif"] != 0 else 'N/A'}
J_IF5: {indicators['sciif5'] if indicators["sciif"] != 0 else 'N/A'}
J_JCI: {indicators['jci'] if indicators["jci"] != 0 else 'N/A'}
Keywords:
{keywords_yaml if keywords_yaml else '  - "N/A"'}
Methods:
{methods_yaml if methods_yaml else '  - "N/A"'}
Data:
{data_yaml if data_yaml else '  - "N/A"'}
Context:
{context_yaml if context_yaml else '  - "N/A"'}
Logic_type: "[[🧠 Type {props.get('Logic Type', 'G')}]]"
Overall: {props.get('Overall', '')}
Relevance: {props.get('Relevance', '')}
Copy_potential: {props.get('Copy Pttl', '')}
Context_transit_potential: {props.get('Cnxt Trnst Pttl', '')}
Method_transit_potential: {props.get('Mthd Trnst Pttl', '')}
DOI: {doi_link}
Local_path: {obsidian_file_link}
---
{md_content}
"""
    # 综述文章
    elif literature_type == "Review":
        obsidian_note = f"""---
Title: "{smart_format(props.get('Title Full', 'Untitled'))}"
Aliases: ["{smart_format(props.get('Title Short EN', ''))}", "{props.get('Title Short CN', '')}"]
Year: {props.get('Year', 'Unknown')}
Authors:
{authors_yaml if authors_yaml else '  - "N/A"'}
Journal: "[[📓 {props.get('Journal', 'N/A')}]]"
Journal_ranks:
{journal_ranks_yaml}
J_IF: {indicators['sciif'] if indicators["sciif"] != 0 else 'N/A'}
J_IF5: {indicators['sciif5'] if indicators["sciif"] != 0 else 'N/A'}
J_JCI: {indicators['jci'] if indicators["jci"] != 0 else 'N/A'}
Keywords:
{keywords_yaml if keywords_yaml else '  - "N/A"'}
Fields:
{fields_yaml if fields_yaml else '  - "N/A"'}
Literature sources:
{lit_src_yaml if lit_src_yaml else '  - "N/A"'}
Filter used:
{filter_yaml if filter_yaml else '  - "N/A"'}
Methods summarized:
{methods_yaml if methods_yaml else '  - "N/A"'}
Data summarized:
{data_yaml if data_yaml else '  - "N/A"'}
Contexts summarized:
{context_yaml if context_yaml else '  - "N/A"'}
Suggestion: "[[👉 {props.get('Suggestion', 'G')}]]"
Relevance: {props.get('Relevance', '')}
Literature quality: {props.get('Lit Qlt', '')}
Field intro value: {props.get('Fld Value', '')}
Dictionary value: {props.get('Dict Value', '')}
Inspiration value: {props.get('Insp Value', '')}
DOI: {doi_link}
Local_path: {obsidian_file_link}
---
{md_content}
"""

    # 提取并生成各类实体，⚠️ 只要有标签 [[]]，就必须要有实体！这样才能筛选对应节点！
    create_entity("👤", props.get("Authors", []), "Authors")
    create_entity("🛠️", props.get("Method Tags", []), "Methods")
    create_entity("📊", props.get("Data Tags", []), "Data")
    create_entity("🗺️", props.get("Context Tags", []), "Contexts")
    create_entity("🔑", props.get("Keywords", []), "Keywords")
    create_entity("🎖️", journal_ranks, "Journal_ranks")
    create_entity("📓", props.get("Journal", []), "Journals")
    # 独属实证文章的
    if literature_type == "Empirical":
        create_entity("🧠 Type ", props.get("Logic Type", []), "Logic_types")
    elif literature_type == "Review":
        create_entity("🌐", props.get("Fields", []), "Fields")
        create_entity("📚", props.get("Lit Src Tags", []), "Literature_sources")
        create_entity("🔍", props.get("Filter Tags", []), "Filters")
        create_entity("👉", props.get("Suggestion", []), "Suggestion")

    # 4. 写入本地文件
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(obsidian_note)
        # 返回结果
        print(f"   ✅ 成功保存本地 .md 文件: {safe_title} - {first_author}.md，及相关实体文件！")
        return True
    except Exception as e:
        print(f"   ❌ 本地 Markdown 保存失败: {e}")
        return False

# region 第4步：输出为 .bib 文献记录，用于导入Zotero
def save_bibtex(data, pdf_local_path, bib_file_with_timestamp):
    print(f"4️⃣ 正在生成 BibTeX 记录...")

    if not os.path.exists(BIBTEX_FOLDER): os.makedirs(BIBTEX_FOLDER)
    
    # 总的 bibtex 文件路径，加上时间戳
    Master_bibtex = os.path.join(BIBTEX_FOLDER, bib_file_with_timestamp)
    
    # 编辑 Zotero 可以识别的 bibtex url 字段，一键连接到 obsidian 相应的 .md 文件
    title_short_cn = data.get("properties", {}).get("Title Short CN", "")
    obsidian_link = "{" + f"http://localhost:18888/obsidian?file={title_short_cn}&vault={OBSIDIAN_VAULT}" + "}"
    
    # 编辑 Zotero 可以识别的 bibtex file 字段
    fake_file_path = os.path.abspath(pdf_local_path).replace("\\", "\\\\").replace(":", "\\:")
    file_link = "{PDF:" + f"{fake_file_path}" + ":application/pdf}"

    # 获取 bibtex code
    bibtex_code = data.get("BibTeX", "")

    try:
        if bibtex_code and bibtex_code.strip() != "N/A":
            # 给 bibtex 增加 obsidian url 和 Zotero file link
            bibtex_code = f"{bibtex_code[:-1]},url={obsidian_link},file={file_link},shorttitle=" + "{" + f"{title_short_cn}" + r"}}"
            # 使用 append 模式，追加到大 bibtex 文件末尾
            with open(Master_bibtex, "a", encoding='utf-8') as f:
                f.write(bibtex_code + "\n\n")
            print (f"   ✅ 已将 BibTex 记录追加至 {Master_bibtex}。")
            return True
        else:
            print("    ❌ 未能从 JSON 中获取有效的 BibTeX 数据。")
            return False
    except json.JSONDecodeError as e:
        print(f"   ❌ 解析失败: {e}")
        return False
    except Exception as e:
        print(f"   ❌ 其他错误: {e}")
        return False

# region 第5步：导入到 Notion
def push_to_notion(data, pdf_local_path, journal_ranks, indicators, literature_type):
    print("5️⃣ 正在推送数据到 Notion...")
    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    
    props = data.get("properties", {})
    markdown_content = data.get("markdown_content", "无内容")

    # 获取绝对路径并进行 URL 编码（防止路径里的空格或中文导致链接断裂）
    abs_path = os.path.abspath(pdf_local_path)
    # 将 Windows 的反斜杠 \ 统一替换为正斜杠 /，防止 URL 解析错误
    abs_path = abs_path.replace("\\", "/")
    encoded_path = urllib.parse.quote(abs_path)
    # 使用我们专属的协议
    custom_link = f"http://localhost:18888/open?path={encoded_path}"

    # 处理 journal_ranks
    ranks = ""
    if journal_ranks[0] != "N/A":
        for rank in journal_ranks:
            ranks +=  f"{rank}; "
        ranks = ranks[:-2]
    else:
        ranks = "N/A"

    # 生成 Notion 数据库属性，分类别
    # 实证文章：
    if literature_type == "Empirical":
        notion_properties = {
            "Title Full": {"title": [{"text": {"content": smart_format(props.get("Title Full", "Untitled"))[:2000]}}]},
            "Title Short EN": {"rich_text": [{"text": {"content": smart_format(props.get("Title Short EN", ""))[:2000]}}]},
            "Title Short CN": {"rich_text": [{"text": {"content": str(props.get("Title Short CN", ""))[:2000]}}]},
            "Authors": {"multi_select": [{"name": str(a).replace(',', '').title()} for a in props.get("Authors", [])]},
            "J Ranks": {"rich_text": [{"text": {"content": ranks}}]},
            "Journal": {"rich_text": [{"text": {"content": str(props.get("Journal", ""))[:2000]}}]},
            "IF": {"number": indicators["sciif"]},
            "IF5": {"number": indicators["sciif5"]},
            "JCI": {"number": indicators["jci"]},
            "Logic Type": {"select": {"name": str(props.get("Logic Type", "G"))}},
            "Keywords": {"multi_select": [{"name": smart_format(str(t).replace(',', ''))} for t in props.get("Keywords", [])]},
            "Data Tags": {"multi_select": [{"name": smart_format(str(t).replace(',', ''))} for t in props.get("Data Tags", [])]},
            "Method Tags": {"multi_select": [{"name": smart_format(str(t).replace(',', ''))} for t in props.get("Method Tags", [])]},
            "Context Tags": {"multi_select": [{"name": smart_format(str(t).replace(',', ''))} for t in props.get("Context Tags", [])]},
            "Local Path": {"url": custom_link} # 自动注入本地绝对路径！
        }
        DATABASE_ID = DATABASE_ID_EMP
    elif literature_type == "Review":
        notion_properties = {
            "Title Full": {"title": [{"text": {"content": smart_format(props.get("Title Full", "Untitled"))[:2000]}}]},
            "Title Short EN": {"rich_text": [{"text": {"content": smart_format(props.get("Title Short EN", ""))[:2000]}}]},
            "Title Short CN": {"rich_text": [{"text": {"content": str(props.get("Title Short CN", ""))[:2000]}}]},
            "Authors": {"multi_select": [{"name": str(a).replace(',', '')} for a in props.get("Authors", [])]},
            "J Ranks": {"rich_text": [{"text": {"content": ranks}}]},
            "Journal": {"rich_text": [{"text": {"content": str(props.get("Journal", ""))[:2000]}}]},
            "IF": {"number": indicators["sciif"]},
            "IF5": {"number": indicators["sciif5"]},
            "JCI": {"number": indicators["jci"]},
            "Keywords": {"multi_select": [{"name": smart_format(str(t).replace(',', ''))} for t in props.get("Keywords", [])]},
            "Fields": {"multi_select": [{"name": smart_format(str(p).replace(',', ''))} for p in props.get("Fields", [])]},
            "Lit Src Tags": {"multi_select": [{"name": smart_format(str(r).replace(',', ''))} for r in props.get("Lit Src Tags", [])]},
            "Filter Tags": {"multi_select": [{"name": smart_format(str(b).replace(',', ''))} for b in props.get("Filter Tags", [])]},
            "Data Tags": {"multi_select": [{"name": smart_format(str(t).replace(',', ''))} for t in props.get("Data Tags", [])]},
            "Method Tags": {"multi_select": [{"name": smart_format(str(t).replace(',', ''))} for t in props.get("Method Tags", [])]},
            "Context Tags": {"multi_select": [{"name": smart_format(str(t).replace(',', ''))} for t in props.get("Context Tags", [])]},
            "Suggestion": {"select": {"name": str(props.get("Suggestion", "0"))}},
            "Local Path": {"url": custom_link} # 自动注入本地绝对路径！
        }
        DATABASE_ID = DATABASE_ID_REV

    # 处理 Year (保持 number 数字类型)
    if props.get("Year"):
        try:
            notion_properties["Year"] = {"number": int(props["Year"])}
        except ValueError:
            pass
    
    # 处理评分 (适配你 Notion 里的 select 单选标签类型)
    if literature_type == "Empirical":
        for score_col in ["Relevance", "Copy Pttl", "Overall", "Cnxt Trnst Pttl", "Mthd Trnst Pttl"]:
            if props.get(score_col):
                notion_properties[score_col] = {"select": {"name": str(props[score_col])}}
    elif literature_type == "Review":
        for score_col in ["Relevance", "Lit Qlt", "Fld Value", "Dict Value", "Insp Value"]:
            if props.get(score_col):
                notion_properties[score_col] = {"select": {"name": str(props[score_col])}}

    # 智能 DOI/URL 处理
    doi_val = str(props.get("DOI", "")).strip()
    if doi_val and doi_val.upper() != "N/A":
        # 如果看起来是个纯 DOI 号，帮它加上网址前缀
        if doi_val.startswith("10."):
            doi_val = f"https://doi.org/{doi_val}"
        # 确保是合法链接才放入，否则丢弃，保护 API 不报错
        if doi_val.startswith("http"):
            notion_properties["DOI/Link"] = {"url": doi_val}

    # === 支持 Mermaid 的究极 Markdown 解析器 ===
    blocks = []
    # 按行分割数据
    lines = markdown_content.split('\n')
    
    in_mermaid = False
    mermaid_code = []

    for line in lines:
        raw_line = line.strip()
        
        # 拦截 Mermaid 代码块的开始
        if raw_line.startswith('```mermaid'):
            in_mermaid = True
            continue
        # 拦截 Mermaid 代码块的结束，并组装成 Notion 专属的 Code Block
        elif in_mermaid and raw_line.startswith('```'):
            in_mermaid = False
            blocks.append({
                "object": "block",
                "type": "code",
                "code": {
                    "rich_text": [{"type": "text", "text": {"content": "\n".join(mermaid_code)[:2000]}}],
                    "language": "mermaid" # 触发 Notion 魔法
                }
            })
            mermaid_code = []
            continue
            
        # 如果正在收集 Mermaid 代码，就原样保存
        if in_mermaid:
            mermaid_code.append(line) # 保留原始缩进
            continue

        # 以下为普通 Markdown 解析
        if not raw_line:
            continue
            
        chunk = raw_line[:2000]
        
        if chunk.startswith('## '):
            blocks.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": chunk[3:].strip()}}]}})
        elif chunk.startswith('### '):
            blocks.append({"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"type": "text", "text": {"content": chunk[4:].strip()}}]}})
        elif chunk.startswith('- ') or chunk.startswith('* '):
            blocks.append({"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": chunk[2:].strip()}}]}})
        else:
            clean_chunk = chunk.replace('**', '') 
            blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": clean_chunk}}]}})
    # ===============================================

    payload = {
        "parent": {"database_id": DATABASE_ID},
        "properties": notion_properties,
        "children": blocks[:100] 
    }

    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        print("   ✅ 推送 Notion 成功！")
        return True
    else:
        print(f"   ❌ 推送 Notion 失败: {response.text}")
        return False

# region 第6步：重命名并移动 PDF
def rename_pdf(data, PROCESSED_FOLDER):
    # 获取 JSON 的中文短标题
    raw_title_short_cn = data.get("properties", {}).get("Title Short CN", "Untitled")

    # 获取 JSON 的第一个作者
    authors = data.get("properties", {}).get("Authors", [])
    
    # 拼接作者 + 中文短标题成为新的 rename 文件名
    new_name_pdf = f"{raw_title_short_cn} - {authors[0]}.pdf"

    # 检查并去除 rename_pdf 中任何可能的对于 Windows 非法的字符
    new_name_pdf = new_name_pdf.strip()
    for char in ['<', '>', ':', '"', '/', '\\', '|', '?', '*']:
        new_name_pdf = new_name_pdf.replace(char, '_')

    # 重命名 pdf_path 里的 PDF 文件为 PROCESSED_FOLDER 里的 PDF 文件
    pdf_path_processed = os.path.join(PROCESSED_FOLDER, new_name_pdf)
    
    # 返回重命名后的 pdf_path_processed
    return pdf_path_processed

# 移动 PDF
def move_pdf(pdf_path, pdf_path_processed):
    print("6️⃣ 正在移动 PDF 文件...")
    
    # 检查 pdf_path_processed 是否存在，并移动
    if os.path.exists(pdf_path):
        if not os.path.exists(pdf_path_processed):
            shutil.move(pdf_path, pdf_path_processed)
    
    print(f"   ✅ 已将 PDF 文件移至 Processed 文件夹：{pdf_path_processed}")
# endregion


# region 主函数
def main():
    literature_type = get_user_input()

    # 读取对应的路径，使用对应的key启动客户端，赋值对应的Prompt
    if literature_type == "Empirical":
        INPUT_FOLDER = INPUT_FOLDER_EMP
        PROCESSED_FOLDER = PROCESSED_FOLDER_EMP
        HASH_DB_FILE = HASH_DB_FILE_EMP
        # 初始化客户端
        client = genai.Client(api_key=GEMINI_API_KEY_EMP)
        MASTER_PROMPT = PROMPT_EMP
        # 总的 bibtex 文件名，加上时间戳
        bib_filename_with_timestamp = rf"{datetime.datetime.now().strftime('%Y%m%d_%H%M')}_Master_Bib.bib"
    elif literature_type == "Review":
        INPUT_FOLDER = INPUT_FOLDER_REV
        PROCESSED_FOLDER = PROCESSED_FOLDER_REV
        HASH_DB_FILE = HASH_DB_FILE_REV
        # 初始化客户端
        client = genai.Client(api_key=GEMINI_API_KEY_REV)
        MASTER_PROMPT = PROMPT_REV
        # 总的 bibtex 文件名，加上时间戳
        bib_filename_with_timestamp = rf"Review_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}_Master_Bib.bib"

    # 确保路径存在
    if not os.path.exists(INPUT_FOLDER): os.makedirs(INPUT_FOLDER)
    if not os.path.exists(PROCESSED_FOLDER): os.makedirs(PROCESSED_FOLDER)
    if not os.path.exists(OBSIDIAN_FOLDER): os.makedirs(OBSIDIAN_FOLDER)
    if not os.path.exists(BIBTEX_FOLDER): os.makedirs(BIBTEX_FOLDER)

    # 循环显示篇数的迭代值
    i_paper = 1

    # 读取 Input 目录下的 PDF 文件列表
    pdf_files = [f for f in os.listdir(INPUT_FOLDER) if f.lower().endswith('.pdf')]
    print("=" * 40)
    if not pdf_files:
        print("📭 Input 文件夹中没有找到 PDF 文件。")
        return
    print(f"🎯 找到 {len(pdf_files)} 篇待处理文献。开始运行自动化流程...")
    print("-" * 40)

    # 开始循环
    for pdf_file in pdf_files:
        # 获取并设定当前篇的原路径和输出路径
        pdf_path = os.path.join(INPUT_FOLDER, pdf_file)
        
        # 检查是否重复
        print(f"0️⃣ 已获取第 {i_paper} 篇PDF文件: {os.path.basename(pdf_path)}！\n   正在用 MD5 哈希值检测该论文是否重复...")
        file_hash = get_file_md5(pdf_path)
        if is_duplicate(file_hash, HASH_DB_FILE):
            print(f"   ⏩ 该论文已重复，将被跳过！")
            # 移动到重复文件夹内
            try:
                shutil.move(pdf_path, os.path.join(f"{PROCESSED_FOLDER}/Repeated", pdf_file))
                print(f"   ✅ 已将重复文件移动至 Processed/Repeated_Papers 文件夹。")
            except Exception as e:
                print(f"   ⚠️ 移动重复文件失败：{e}，请注意检查 Input 路径！\n  即将开始分析下一篇...")
            
            print("-" * 40)
            i_paper += 1
            continue #直接跳过，进入下一个循环
        else:
            print("   ✅ 未发现重复，开始分析...")         

        # 调用大模型并获取返回的 JSON
        result_json = get_paper_analysis(MASTER_PROMPT, pdf_path, client)

        if result_json and result_json != "NAP" and result_json != "FW":
            # 根据获取到的中文短标题，设置输出 PDF 路径
            pdf_path_processed = rename_pdf(result_json, PROCESSED_FOLDER)
            
            # 获取期刊等级
            journal_name = result_json.get("properties", {}).get("Journal", "")
            journal_ranks, indicators = get_journal_ranks(journal_name)

            # 优先保存一份到本地 Obsidian 文件夹
            success1 = save_to_obsidian(result_json, pdf_path_processed, journal_ranks, indicators, literature_type)
            
            # 提取Bibtex并追加到本地引用文件中
            success2 = save_bibtex(result_json, pdf_path_processed, bib_filename_with_timestamp)

            # 推送到 Notion
            success3 = push_to_notion(result_json, pdf_path_processed, journal_ranks, indicators, literature_type)

            # 如果前面几步都成功完成，移动文件并保存哈希值
            if success1 and success2 and success3:
                move_pdf(pdf_path, pdf_path_processed)
                record_hash(file_hash, HASH_DB_FILE)
            else:
                steps = [
                    (success1, "保存到 Obsidian 失败"),
                    (success2, "保存 Bibtex 失败"),
                    (success3, "推送 Notion 失败"),
                ]
                failed = [step[1] for step in steps if not step[0]]
                print(f"   ❌ 未移动文件，原因：{', '.join(failed)}。\n   ⚠️ 注意检查其他环节的生成结果！必要时将其删除！")
        elif result_json == "NAP":
            print("   ⚠️经过LLM分析，该PDF文件内容并非学术论文！将跳过并分析下一篇！")
        elif result_json == "FW":
            print("   ⚠️LLM无法打开或无法读取该PDF文件！将跳过并分析下一篇！")

        if not i_paper == len(pdf_files):
            i_paper += 1   
            print("☕ 为避免触发免费额度限制，休眠 70 秒...")
            time.sleep(70)
            print("-" * 40)
        else:
            print("-" * 40)
    
    print("🎉 全部任务执行完毕！")
    print("=" * 40)

    #region 以下是调试代码，实际使用时保持注释状态即可
    
    # 🔴 这是一份完美符合我们 Prompt 要求的假 JSON 数据
    # result_json = {
    #     "properties": {
    #     "Title Full": "The global homogenization of urban form. An assessment of 194 cities across time",
    #     "Title Short EN": "Global Homogenization Urban Form",
    #     "Title Short CN": "城市更新对地方依恋影响的研究框架",
    #     "Year": 2024,
    #     "Authors": ["Michael Batty", "John Doe"],
    #     "Journal": "Frontiers of Architectural Research",
    #     "Logic Type": "B",
    #     "Keywords": ["SVI", "Clustering"],
    #     "Data Tags": ["SVI", "Clustering"],
    #     "Method Tags": ["SVI", "Clustering"],
    #     "Context Tags": ["SVI", "Clustering"],
    #     "DOI": "10.1016/j.cities.2026.106897",
    #     "Relevance": 5,
    #     "Copy Pttl": 4,
    #     "Cnxt Trnst Pttl": 3,
    #     "Mthd Trnst Pttl": 3,
    #     "Overall": 4
    #     },
    #     "BibTeX": "@article{zhang2024quantifying,\n  title={Quantifying the morphological evolution of historical districts using deep learning and street view imagery},\n  author={Zhang, Wei and Batty, Michael and Li, Xia},\n  journal={Computers, Environment and Urban Systems},\n  volume={105},\n  pages={102000},\n  year={2024},\n  publisher={Elsevier},\n  doi={10.1016/j.compenvurbsys.2024.102000},\n  keywords={★5_Overall, ★5_Relevance, CNN, SVI}\n}",
    #     "markdown_content": "## 1. 逻辑类型判定\n类型 B 分类/模式识别型\n\n## 2. 核心范式公式\n```mermaid\ngraph TB\n    A[开源数据爬取] --> B[NLP量化语义]\n    B --> C[K-Means聚类]\n    C --> D[识别空间模式]\n```\n\n## 3. 方法与工具拆解\n* 原始数据采集: 爬取OSM开源数据\n* 数据预处理/结构化: 转化为路网矩阵\n* 数据清洗: 剔除断头路\n* 特征提取: 计算中心度\n* 核心模型/空间分析: K-Means聚类\n* 因果推断/解释: 原文未明确说明\n* 数据及结果可视化: 使用散点图和地图展示分类结果\n\n## 4. 关键要素速览\n* 研究对象: 全球194个城市的形态数据\n* 理论锚点: 城市形态学理论\n* 研究目标: 揭示全球城市形态的演变规律\n* 核心研究问题: 全球城市形态是否随时间趋于同质化？\n* 核心结论: 是的，存在显著的同质化趋势。\n* 数据源的可获取性: 开源免费\n\n## 5. 对我的价值评估\n* 相关度: 5分，与我的历史城市形态研究高度相关。\n* 复刻难度: 3分，数据开源，聚类算法基础，可尝试复刻。\n* 核心启示: 跨城市大样本对比的方法非常新颖。\n* 场景迁移潜力: 可以将此聚类方法平移到国内历史文化名城的形态对比上。\n* 技术热插拔潜力: 原文的K-Means较老，可以尝试用深度聚类算法替换。\n* 真实缺陷与改进潜力: 缺乏对文化语义的深入探讨，可以结合NLP进行改进。\n\n## 6. 最终推荐决议\n4分，强烈建议略读了解其数据构建和对比框架。"
    # }

    # # 🔴 以下是 Notion 本地断点调试代码 ============================
    #region
    # print("🛠️ 开启 Notion 本地断点调试，完全跳过大模型 API...")
    
    # dummmy_path = "H:\OneDrive - Qian Liu\OneDrive\! Literature Reports\Data-driven Literature\Processed\英文原版_The global homogenization of urban form. An assessment of 194 cities across time.pdf"

    # # 直接将假数据喂给 Notion 推送函数，0 消耗测试！
    # success = push_to_notion(dummy_json, dummmy_path)
    
    # if success:
    #     print("🎉 调试成功！快去 Notion 看看排版是不是完美了！\n")
    # else:
    #     print("❌ 调试失败，请查看具体报错。\n")
    #endregion
    # # =======================================================

    # # 🔴 以下是 Obsidian 本地断点调试代码 ==========================
    #region
    # print("🛠️ 开启 Obsidian 本地断点调试，完全跳过大模型 API...")

    # dummmy_path = "H:\OneDrive - Qian Liu\OneDrive\! Literature Reports\Data-driven Literature\Processed\The global homogenization of urban form. An assessment of 194 cities across time.pdf"

    # # 直接将假数据喂给 Notion 推送函数，0 消耗测试！
    # success = save_to_obsidian(dummy_json, dummmy_path)
    
    # if success:
    #     print("🎉 调试成功！快去 Bibtex 文件夹看看！\n")
    # else:
    #     print("❌ 调试失败，请查看具体报错。\n")
    #endregion
    # #========================================================

    # # 🔴 以下是 bibtex 本地断点调试代码 version 1 =========================================================
    #region
    # print("🛠️ 开启 Bibtex 本地断点调试，完全跳过大模型 API...")
    
    # dummy_filename = "1-s2.0-S0264275126001265-main.pdf"

    # if not os.path.exists(BIBTEX_FOLDER): os.makedirs(BIBTEX_FOLDER)
    
    # # 创建一个大的 bibtex 文件，加上时间戳
    # bib_filename = rf"{datetime.datetime.now().strftime('%Y%m%d_%H%M')}_Master_Bib.bib"
    # Master_bibtex = os.path.join(BIBTEX_FOLDER, bib_filename)
    
    # # 编辑 Zotero 可以识别的 bibtex url 字段，一键连接到 obsidian 相应的 .md 文件
    # title_short_cn = dummy_json.get("properties", {}).get("Title Short CN", "")
    # obsidian_link = "{" + f"http://localhost:18888/obsidian?file={title_short_cn}&vault={OBSIDIAN_VAULT}" + "}"
    
    # # 编辑 Zotero 可以识别的 bibtex file 字段
    # fake_file_path = os.path.abspath(f"{PROCESSED_FOLDER}\{dummy_filename}").replace("\\", "\\\\").replace(":", "\\:")
    # file_link = "{PDF:" + f"{fake_file_path}" + ":application/pdf}"

    # print(f"4️⃣ 正在生成 BibTeX 记录...")
    # # 获取 bibtex code 并添加 obsidian 链接
    # bibtex_code = dummy_json.get("BibTeX", "")

    # try:
    #     if bibtex_code and bibtex_code.strip() != "N/A":
    #         # 使用 append 模式，追加到大 bibtex 文件末尾
    #         bibtex_code = f"{bibtex_code[:-2]},\n  url={obsidian_link},\n  file={file_link}{bibtex_code[-2:]}"
    #         with open(Master_bibtex, "a", encoding='utf-8') as f:
    #             f.write(bibtex_code + "\n\n")
    #         print (f"   ✅ 已将 BibTex 记录追加至 {Master_bibtex}。")
    #     else:
    #         print("    ❌ 未能从 JSON 中获取有效的 BibTeX 数据。")
    # except json.JSONDecodeError as e:
    #     print(f"   ❌ 解析失败: {e}")
    #endregion
    # #=====================================================================================

    # # 🔴 以下是 bibtex 本地断点调试代码 version 2 =========================================================
    #region
    # print("🛠️ 开启 Bibtex 本地断点调试，完全跳过大模型 API...")
    
    # dummy_pdf_local_path = "./Processed/1-s2.0-S0264275126001265-main.pdf"
    
    # # 创建一个大的 bibtex 文件，加上时间戳
    # dummy_bib_filename_with_timestamp = rf"{datetime.datetime.now().strftime('%Y%m%d_%H%M')}_Master_Bib.bib"

    # success = save_bibtex(dummy_json, dummy_pdf_local_path, dummy_bib_filename_with_timestamp)
    
    # if success:
    #     print("🎉 调试成功！快去 Bibtex 文件夹看看！\n")
    # else:
    #     print("❌ 调试失败，请查看具体报错。\n")
    #endregion
    # #=====================================================================================
    #endregion

if __name__ == "__main__":
    main()