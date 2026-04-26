# 檔名：app.py
import os
import requests
import threading
import base64
from flask import Flask, request, jsonify
from gtts import gTTS
import subprocess
import imageio_ffmpeg

app = Flask(__name__)

# 🚨 請填入您「全新申請」的金鑰 🚨
FAL_API_KEY = "588b10cb-603e-494e-96b3-66aed77ae983:b13610c75dcccb2c674df50248152692"
LORA_URL = "https://v3b.fal.media/files/b/0a97b6f3/HhMceWpJdTP7Fkz6_LHLk_pytorch_lora_weights.safetensors"
GAS_WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbzxxDJqDigH-9NK8XUUeOiX0NDkBRGaGIc4Z_m-2Q5bzPZT2aEh0zvI-MIkSQoUf90y/exec" 

# 🧠 系統記憶體：用來記住還沒開拍的劇本
PENDING_SCENES = {}

# ==========================================
# 🎬 上半場：批次生圖與選角 (收到 GAS 劇本後執行)
# ==========================================
def process_images_background(scene_data):
    try:
        scene_id = scene_data['scene_id']
        print(f"🚀 [上半場] 啟動：正在為場景 {scene_id} 生成 4 張候選圖...")
        
        # 把劇本存入記憶體，等主任選圖後下半場還要用
        PENDING_SCENES[scene_id] = scene_data

        headers = {"Authorization": f"Key {FAL_API_KEY}", "Content-Type": "application/json"}

        # 1. 呼叫 Fal.ai 一次生成 4 張圖
        img_payload = {
            "prompt": scene_data['prompt'], 
            "image_size": "landscape_16_9", 
            "num_images": 4,  # 🌟 關鍵：一次產出 4 張變體
            "loras": [{"path": LORA_URL, "scale": 1.0}]
        }
        img_resp = requests.post("https://fal.run/fal-ai/flux-lora", json=img_payload, headers=headers)
        
        if img_resp.status_code != 200:
            raise Exception(f"生圖失敗！原因：{img_resp.text}")
            
        # 取得 4 張圖的網址
        img_urls = [img['url'] for img in img_resp.json()['images']]
        print(f"🎨 4 張候選圖生成完畢，準備送回 GAS 導演台...")

        # 2. 將 4 張圖打包送回 GAS Webhook
        payload = {
            "type": "preview_options",
            "scene_id": scene_id,
            "options": img_urls,
            "script": scene_data
        }
        requests.post(GAS_WEBHOOK_URL, json=payload)
        print("📦 候選圖已成功送達導演控制台！等待主任審核...")

    except Exception as e:
        print(f"❌ [上半場] 錯誤：{e}")


# ==========================================
# 🎬 下半場：動畫生成與後製 (收到主任確認後執行)
# ==========================================
def process_video_background(scene_id, confirmed_image):
    try:
        print(f"🚀 [下半場] 啟動：主任已核准場景 {scene_id}，開始生成動畫...")
        
        # 從記憶體中喚醒原本的劇本
        scene_data = PENDING_SCENES.get(scene_id)
        if not scene_data:
            raise Exception("找不到該場景的劇本記憶，可能伺服器曾重啟，請重新發送劇本。")

        headers = {"Authorization": f"Key {FAL_API_KEY}", "Content-Type": "application/json"}

        # 1. 影片生成 (使用主任挑選的那張圖)
        print("-> 🎥 正在將圖片轉為 3D 動畫...")
        vid_payload = {"image_url": confirmed_image, "prompt": scene_data['video_prompt']}
        vid_resp = requests.post("https://fal.run/fal-ai/minimax-video/image-to-video", json=vid_payload, headers=headers)
        
        if vid_resp.status_code != 200:
            raise Exception(f"動畫失敗！原因：{vid_resp.text}")
            
        video_url = vid_resp.json()['video']['url']
        video_filename = f"raw_video_{scene_id}.mp4"
        with open(video_filename, 'wb') as f:
            f.write(requests.get(video_url).content)

        # 2. 語音生成
        print("-> 🎙️ 正在生成語音...")
        audio_filename = f"scene_{scene_id}.mp3"
        gTTS(text=scene_data['dialogue'], lang='en', slow=False).save(audio_filename)

        # 3. 極速模式剪輯
        print("-> 🎞️ 正在進行最終剪輯...")
        output_filename = f"final_scene_{scene_id}.mp4"
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        
        command = [
            ffmpeg_exe, "-y",
            "-i", video_filename, "-i", audio_filename,
            "-c:v", "copy", "-c:a", "aac",
            "-map", "0:v:0", "-map", "1:a:0",
            "-shortest", output_filename
        ]
        subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # 4. 上傳 GoFile
        print(f"✅ 渲染完成！上傳 GoFile 雲端空間...")
        server_req = requests.get("https://api.gofile.io/servers")
        server_name = server_req.json()['data']['servers'][0]['name']
        upload_url = f"https://{server_name}.gofile.io/contents/uploadfile"
        
        with open(output_filename, 'rb') as f:
            upload_resp = requests.post(upload_url, files={'file': f})
        
        download_link = upload_resp.json()['data']['downloadPage']
        
        # 5. 回報最終網址給 GAS
        payload = {
            "type": "final_video",
            "filename": output_filename,
            "video_url": download_link
        }
        requests.post(GAS_WEBHOOK_URL, json=payload)
        print(f"📦 最終動畫網址已回報給 GAS！連結：{download_link}")

        # 6. 清理環境
        os.remove(audio_filename)
        os.remove(video_filename)
        os.remove(output_filename)
        # 清除記憶體
        del PENDING_SCENES[scene_id]

    except Exception as e:
        print(f"❌ [下半場] 錯誤：{e}")


# ==========================================
# 🚪 伺服器接收大門 (API Endpoints)
# ==========================================

# 大門 1：接收新劇本，開始生圖
@app.route('/api/generate', methods=['POST'])
def receive_script():
    data = request.json
    scene_data = data[0]
    thread = threading.Thread(target=process_images_background, args=(scene_data,))
    thread.start()
    return jsonify({"status": "success", "message": "劇本已接收，開始批次生圖！"})

# 大門 2：接收導演選圖確認，開始生動畫
@app.route('/api/start-animation', methods=['POST'])
def start_animation():
    data = request.json
    scene_id = data['scene_id']
    confirmed_image = data['confirmed_image']
    thread = threading.Thread(target=process_video_background, args=(scene_id, confirmed_image,))
    thread.start()
    return jsonify({"status": "success", "message": "導演核准完畢，開拍動畫！"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
