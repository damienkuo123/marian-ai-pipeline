# 檔名：app.py
import os
import requests
import threading
import base64
import json
from flask import Flask, request, jsonify
from gtts import gTTS
import subprocess
import imageio_ffmpeg
import google.generativeai as genai

app = Flask(__name__)

# ✅ 正確的防彈寫法：向環境變數索取金鑰
FAL_API_KEY = os.environ.get("FAL_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)
LORA_URL = "https://v3b.fal.media/files/b/0a97b6f3/HhMceWpJdTP7Fkz6_LHLk_pytorch_lora_weights.safetensors"
GAS_WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbzxxDJqDigH-9NK8XUUeOiX0NDkBRGaGIc4Z_m-2Q5bzPZT2aEh0zvI-MIkSQoUf90y/exec" 

PENDING_SCENES = {}

# ==========================================
# 🧠 全新模組：Gemini AI 編劇大腦
# ==========================================
@app.route('/api/write-script', methods=['POST'])
def write_script():
    data = request.json
    title = data.get('title', '新場次')
    outline = data.get('outline', '')
    chars = data.get('chars', [])
    locs = data.get('locs', [])

    # 將 GAS 傳來的角色與場景資產，組合成給 AI 的參考書
    char_info = "\n".join([f"角色 [{c['Name']}]: {c['Prompt']}" for c in chars])
    loc_info = "\n".join([f"場景 [{l['Name']}]: {l['Prompt']}" for l in locs])

    # 嚴格的系統提示詞 (System Prompt) - 這是確保產出品質的靈魂
    prompt_text = f"""
    You are an expert 3D animation director and storyboard artist.
    Please break down the following Sequence Outline into 3 to 5 cinematic Shots.
    
    【Project Info】
    Sequence Title: {title}
    Outline: {outline}
    
    【Available Assets】
    {char_info}
    {loc_info}
    
    【Output Format】
    You MUST output ONLY a valid JSON array of objects. No markdown formatting, no explanations.
    Each object must have the following keys exactly:
    - "Shot_ID": integer (1, 2, 3...)
    - "Dialogue": string (English dialogue for the character. Leave empty if no dialogue).
    - "Prompt": string (The static image generation prompt. You MUST fuse the Character prompt and Location prompt naturally, and add the specific action. End the prompt with: "High-texture Pixar 3D animation style, cinematic lighting, volumetric fog, realistic material rendering").
    - "Video_Prompt": string (The dynamic motion instruction for the video AI. e.g., "The girl smiles and waves her hand, camera slowly pans right").
    """
    
    try:
        print(f"🧠 正在呼叫 Gemini 拆解分鏡：{title}")
        model = genai.GenerativeModel('gemini-3.1-pro-preview')
        response = model.generate_content(prompt_text)
        
        # 清理可能夾帶的 Markdown 語法 (```json ... ```)
        result_text = response.text.strip()
        if result_text.startswith("```json"):
            result_text = result_text[7:]
        if result_text.endswith("```"):
            result_text = result_text[:-3]
            
        script_json = json.loads(result_text.strip())
        print(f"✅ Gemini 拆解完成，共 {len(script_json)} 個鏡頭。")
        
        return jsonify({"status": "success", "data": script_json})
        
    except Exception as e:
        print(f"❌ Gemini 編劇失敗：{e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ==========================================
# 🎬 上半場：批次生圖與選角
# ==========================================
def process_images_background(scene_data):
    try:
        scene_id = scene_data['scene_id']  # 注意：之後會改成 Shot_ID
        print(f"🚀 [上半場] 啟動：為場景 {scene_id} 生成 4 張候選圖...")
        PENDING_SCENES[scene_id] = scene_data
        headers = {"Authorization": f"Key {FAL_API_KEY}", "Content-Type": "application/json"}

        img_payload = {
            "prompt": scene_data['prompt'], 
            "image_size": "landscape_16_9", 
            "num_images": 4, 
            "loras": [{"path": LORA_URL, "scale": 1.0}]
        }
        img_resp = requests.post("https://fal.run/fal-ai/flux-lora", json=img_payload, headers=headers)
        if img_resp.status_code != 200: raise Exception(img_resp.text)
            
        img_urls = [img['url'] for img in img_resp.json()['images']]
        
        requests.post(GAS_WEBHOOK_URL, json={
            "type": "preview_options", "scene_id": scene_id, "options": img_urls, "script": scene_data
        })
        print("📦 候選圖已成功送達導演控制台！")
    except Exception as e:
        print(f"❌ [上半場] 錯誤：{e}")

# ==========================================
# 🎬 下半場：動畫生成與後製
# ==========================================
def process_video_background(scene_id, confirmed_image):
    try:
        print(f"🚀 [下半場] 啟動：核准場景 {scene_id}...")
        scene_data = PENDING_SCENES.get(scene_id)
        if not scene_data: raise Exception("找不到劇本記憶。")

        headers = {"Authorization": f"Key {FAL_API_KEY}", "Content-Type": "application/json"}

        print("-> 🎥 生成 3D 動畫...")
        vid_payload = {"image_url": confirmed_image, "prompt": scene_data.get('video_prompt', 'natural motion')}
        vid_resp = requests.post("https://fal.run/fal-ai/minimax-video/image-to-video", json=vid_payload, headers=headers)
        if vid_resp.status_code != 200: raise Exception(vid_resp.text)
            
        video_filename = f"raw_video_{scene_id}.mp4"
        with open(video_filename, 'wb') as f: f.write(requests.get(vid_resp.json()['video']['url']).content)

        print("-> 🎙️ 生成語音...")
        audio_filename = f"scene_{scene_id}.mp3"
        dialogue = scene_data.get('dialogue', '')
        if dialogue:
            gTTS(text=dialogue, lang='en', slow=False).save(audio_filename)
        else:
            # 若無台詞，建立一秒的靜音檔避免報錯
            subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "1", "-q:a", "9", "-acodec", "libmp3lame", audio_filename, "-y"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        print("-> 🎞️ 極速剪輯...")
        output_filename = f"final_scene_{scene_id}.mp4"
        subprocess.run([
            imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", video_filename, "-i", audio_filename,
            "-c:v", "copy", "-c:a", "aac", "-map", "0:v:0", "-map", "1:a:0", "-shortest", output_filename
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        print(f"✅ 上傳 GoFile...")
        server_name = requests.get("https://api.gofile.io/servers").json()['data']['servers'][0]['name']
        with open(output_filename, 'rb') as f:
            download_link = requests.post(f"https://{server_name}.gofile.io/contents/uploadfile", files={'file': f}).json()['data']['downloadPage']
        
        requests.post(GAS_WEBHOOK_URL, json={
            "type": "final_video", "scene_id": scene_id, "filename": output_filename, "video_url": download_link
        })
        
        os.remove(audio_filename); os.remove(video_filename); os.remove(output_filename)
        del PENDING_SCENES[scene_id]

    except Exception as e:
        print(f"❌ [下半場] 錯誤：{e}")

# ==========================================
# 🚪 伺服器接收大門
# ==========================================
@app.route('/api/generate', methods=['POST'])
def receive_script():
    data = request.json
    scene_data = data[0]
    threading.Thread(target=process_images_background, args=(scene_data,)).start()
    return jsonify({"status": "success"})

@app.route('/api/start-animation', methods=['POST'])
def start_animation():
    data = request.json
    threading.Thread(target=process_video_background, args=(data['scene_id'], data['confirmed_image'])).start()
    return jsonify({"status": "success"})

# ==========================================
# 🔍 系統雷達：列出所有可用的 Gemini 模型
# ==========================================
@app.route('/api/models', methods=['GET'])
def list_available_models():
    try:
        # 列出所有支援生成內容的模型
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        return jsonify({
            "status": "success", 
            "total_count": len(available_models),
            "available_models": available_models
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# ==========================================
# ✍️ 全新模組：互動式編劇室 (聊天對話)
# ==========================================
@app.route('/api/brainstorm', methods=['POST'])
def brainstorm():
    data = request.json
    user_message = data.get('message', '')
    history = data.get('history', []) # 接收過去的對話紀錄
    
    try:
        model = genai.GenerativeModel('gemini-3.1-pro-preview')
        
        # 💡 如果是第一句話，我們偷偷塞入「首席編劇」的系統指令
        if not history:
            user_message = f"[系統指令：你是瑪麗安動畫工作室的首席編劇。請以專業、有創意的態度與導演討論營隊動畫劇本。協助發想章節大綱，語氣保持專業與簡潔。]\n\n導演說：{user_message}"

        # 啟動具有記憶的聊天室
        chat = model.start_chat(history=history)
        response = chat.send_message(user_message)
        
        # 整理最新歷史紀錄回傳給網頁
        updated_history = [{"role": msg.role, "parts": [msg.parts[0].text]} for msg in chat.history]
            
        return jsonify({"status": "success", "reply": response.text, "history": updated_history})
    except Exception as e:
        print(f"❌ 編劇室發生錯誤：{e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ==========================================
# 🔍 全新模組：資產分析與盤點 (Asset Analysis)
# ==========================================
@app.route('/api/analyze-assets', methods=['POST'])
def analyze_assets():
    data = request.json
    outline = data.get('outline', '')
    available_chars = data.get('chars', [])
    available_locs = data.get('locs', [])

    # 讓 Gemini 擔任場記，盤點需要哪些資產
    prompt_text = f"""
    You are a production manager. Analyze this chapter outline and match it with the available assets.
    Outline: {outline}
    
    Characters in library: {available_chars}
    Locations in library: {available_locs}
    
    Output JSON:
    {{
      "identified_chars": ["Name1", "Name2"],
      "identified_loc": "LocationName",
      "estimated_shots": 5,
      "production_notes": "A brief advice for the director"
    }}
    """
    
    try:
        model = genai.GenerativeModel('gemini-3.1-pro-preview')
        response = model.generate_content(prompt_text)
        # 清理並讀取 JSON (省略清理邏輯...)
        return jsonify({"status": "success", "analysis": json.loads(response.text)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
        
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
