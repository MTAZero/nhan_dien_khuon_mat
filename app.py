from flask import Flask, render_template, Response, request, redirect, url_for, flash
import cv2
import numpy as np
from datetime import datetime
import os
from pymongo import MongoClient
from werkzeug.utils import secure_filename
import json

app = Flask(__name__)
app.secret_key = 'your-secret-key'  # Required for flash messages

# MongoDB connection
MONGODB_URI = "mongodb+srv://mtazero:123edcxz@cluster0.aofke.mongodb.net/attendance_system?authSource=admin&replicaSet=Cluster0-shard-0&w=majority&readPreference=primary&retryWrites=true&ssl=true"
client = MongoClient(MONGODB_URI)
db = client['attendance_system']
students_collection = db['students']
attendance_collection = db['attendance']

# Create necessary directories
UPLOAD_FOLDER = 'static/student_images'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Load face detection model
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

# Mở webcam
camera = cv2.VideoCapture(0)

def generate_frames():
    while True:
        success, frame = camera.read()
        if not success:
            break

        # Chuyển sang grayscale
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Tìm khuôn mặt
        faces = face_cascade.detectMultiScale(gray, 1.3, 5)

        for (x, y, w, h) in faces:
            # Vẽ khung
            cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
            
            # Lấy ảnh khuôn mặt
            face_roi = gray[y:y+h, x:x+w]
            
            # Ghi log điểm danh
            now = datetime.now()
            attendance_record = {
                'timestamp': now,
                'date': now.strftime("%Y-%m-%d")
            }
            
            # Kiểm tra xem đã điểm danh chưa
            existing_attendance = attendance_collection.find_one({
                'date': now.strftime("%Y-%m-%d")
            })
            
            if not existing_attendance:
                attendance_collection.insert_one(attendance_record)
                print(f"Đã điểm danh lúc {now}")

        # Encode frame thành JPEG
        ret, buffer = cv2.imencode('.jpg', frame)
        frame = buffer.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/students')
def students():
    students_list = list(students_collection.find())
    return render_template('students.html', students=students_list)

@app.route('/add_student', methods=['POST'])
def add_student():
    if 'student_image' not in request.files:
        flash('Không tìm thấy file ảnh')
        return redirect(url_for('index'))
    
    file = request.files['student_image']
    if file.filename == '':
        flash('Không có file được chọn')
        return redirect(url_for('index'))

    if file:
        filename = secure_filename(file.filename)
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(file_path)

        # Thêm sinh viên vào database
        student = {
            'student_id': request.form['student_id'],
            'name': request.form['student_name'],
            'image_path': filename
        }
        
        # Kiểm tra xem mã sinh viên đã tồn tại chưa
        if students_collection.find_one({'student_id': student['student_id']}):
            flash('Mã sinh viên đã tồn tại')
            os.remove(file_path)  # Xóa ảnh đã upload
            return redirect(url_for('index'))
        
        students_collection.insert_one(student)
        flash('Thêm sinh viên thành công')
        return redirect(url_for('students'))

@app.route('/delete_student/<student_id>', methods=['POST'])
def delete_student(student_id):
    student = students_collection.find_one({'student_id': student_id})
    if student:
        # Xóa ảnh
        image_path = os.path.join(UPLOAD_FOLDER, student['image_path'])
        if os.path.exists(image_path):
            os.remove(image_path)
        
        # Xóa sinh viên khỏi database
        students_collection.delete_one({'student_id': student_id})
        flash('Xóa sinh viên thành công')
    return redirect(url_for('students'))

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == "__main__":
    app.run(debug=True)