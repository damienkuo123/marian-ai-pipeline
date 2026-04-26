# 檔名：app.py
import os
import requests
import threading
import base64  # 🌟 補上這個必要的導入
from flask import Flask, request, jsonify
from gtts import gTTS
from moviepy.editor import VideoFileClip, AudioFileClip

app = Flask(__name__)

# 🚨 填入您的金鑰 🚨
FAL_API_KEY = "588b10cb-603e-494e-96b3-66aed77ae983:b13610c75dcccb2c674df50248152692"
LORA_URL = "https://v3b.fal.media/files/b/0a97b6f3/HhMceWpJdTP7Fkz6_LHLk_pytorch_lora_weights.safetensors"

def process_video_background(scene_data):
    try:
        print(f"🚀 背景任務啟動：處理場景 {scene_data['scene_id']}")
        headers = {"Authorization": f"Key {FAL_API_KEY}", "Content-Type": "application/json"}

        # 1. 生圖
        print("-> 🎨 正在渲染完美靜態圖...")
        img_payload = {"prompt": scene_data['prompt'], "image_size": "landscape_16_9", "loras": [{"path": LORA_URL, "scale": 1.0}]}
        img_resp = requests.post("https://fal.run/fal-ai/flux-lora", json=img_payload, headers=headers).json()
        img_url = img_resp['images'][0]['url']

        # 2. 影片
        print("-> 🎥 正在將圖片轉為 3D 動畫...")
        vid_payload = {"image_url": img_url, "prompt": scene_data['video_prompt']}
        vid_resp = requests.post("https://fal.run/fal-ai/minimax-video/image-to-video", json=vid_payload, headers=headers).json()
        video_url = vid_resp['video']['url']
        
        video_filename = f"raw_video_{scene_data['scene_id']}.mp4"
        with open(video_filename, 'wb') as f:
            f.write(requests.get(video_url).content)

        # 3. 語音
        print("-> 🎙️ 正在生成語音...")
        audio_filename = f"scene_{scene_data['scene_id']}.mp3"
        gTTS(text=scene_data['dialogue'], lang='en', slow=False).save(audio_filename)

        # 4. 剪輯
        print("-> 🎞️ 正在進行最終剪輯...")
        audio_clip = AudioFileClip(audio_filename)
        raw_video_clip = VideoFileClip(video_filename)
        final_duration = min(audio_clip.duration, raw_video_clip.duration)
        final_video_clip = raw_video_clip.subclip(0, final_duration).set_audio(audio_clip.subclip(0, final_duration))
        
        output_filename = f"final_scene_{scene_data['scene_id']}.mp4"
        final_video_clip.write_videofile(output_filename, fps=24, logger=None)
        
        # --- 物流快遞回 GAS ---
        print(f"✅ 渲染完成！準備將 {output_filename} 送回 Google Drive...")
        
        # 您的 GAS Webhook 網址
        GAS_WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbzR6LE_6wzzdoaKHM80sd01xah6PuGu740UzsDOnRy9kqZhi_GX_qC2CJG6_5Lf8esB/exec" 
        
        with open(output_filename, "rb") as video_file:
            encoded_string = base64.b64encode(video_file.read()).decode('utf-8')
            
        payload = {
            "filename": output_filename,
            "video_base64": encoded_string
        }
        
        deliver_resp = requests.post(GAS_WEBHOOK_URL, json=payload)
        print(f"📦 物流回報: {deliver_resp.text}")

        # 5. 🏠 清理環境：刪除暫存檔，保持伺服器整潔
        audio_clip.close()
        raw_video_clip.close()
        os.remove(audio_filename)
        os.remove(video_filename)
        os.remove(output_filename)
        print("🧹 暫存檔已清理。")
        
    except Exception as e:
        print(f"❌ 錯誤報告：{e}")

@app.route('/api/generate', methods=['POST'])
def receive_script():
    data = request.json
    scene_data = data[0]
    thread = threading.Thread(target=process_video_background, args=(scene_data,))
    thread.start()
    return jsonify({"status": "success", "message": "任務已排入排程！"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
