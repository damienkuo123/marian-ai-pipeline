# 檔名：app.py
import os
import requests
import threading
from flask import Flask, request, jsonify
from gtts import gTTS
from moviepy.editor import VideoFileClip, AudioFileClip

app = Flask(__name__)

# 🚨 填入您的金鑰 🚨
FAL_API_KEY = "YOUR_NEW_FAL_API_KEY"
LORA_URL = "https://v3b.fal.media/files/b/0a97b6f3/HhMceWpJdTP7Fkz6_LHLk_pytorch_lora_weights.safetensors"
# LINE_NOTIFY_TOKEN = "我們下一步再來申請這個"

# 這是真正在背景做苦力的函數 (把您 Colab 的心血搬過來)
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
        
        # 下載影片
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
        
        print(f"✅ 動畫渲染完成！檔案：{output_filename}")
        
        # ⚠️ 未來這裡會加入「將 MP4 上傳 Google Drive」與「發送 LINE 通知」的程式碼 ⚠️

    except Exception as e:
        print(f"❌ 背景任務發生錯誤：{e}")


# 這是伺服器的「大門」，專門接收 GAS 傳來的 JSON
@app.route('/api/generate', methods=['POST'])
def receive_script():
    data = request.json # 接收 GAS 傳來的 JSON 陣列
    scene_data = data[0] # 取出第一個場景
    
    # 把任務丟給背景去跑，不要讓網頁卡住
    thread = threading.Thread(target=process_video_background, args=(scene_data,))
    thread.start()
    
    # 立刻回覆 GAS 網頁：「收到了，正在處理！」
    return jsonify({"status": "success", "message": "任務已成功接收，正在背景處理中！"})


if __name__ == '__main__':
    # 啟動伺服器 (Port 5000)
    app.run(host='0.0.0.0', port=5000)
