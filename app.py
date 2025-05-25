from flask import Flask, render_template, Response, request, redirect, url_for, flash
import cv2
import numpy as np
from datetime import datetime
import os
from pymongo import MongoClient
from werkzeug.utils import secure_filename
import json
import base64
from bson.objectid import ObjectId
import face_recognition

app = Flask(__name__)
app.secret_key = 'your-secret-key'  # Required for flash messages

# MongoDB connection
MONGODB_URI = "mongodb://admin:admin123@localhost:27017/"

try:
    client = MongoClient(MONGODB_URI)
    # Kiểm tra kết nối
    client.admin.command('ping')
    print("Kết nối MongoDB thành công!")
    
    # Chọn database
    db = client['attendance_system']
    students_collection = db['students']
    attendance_collection = db['attendance']
    
except Exception as e:
    print(f"Lỗi kết nối MongoDB: {str(e)}")
    raise e

# Create necessary directories
UPLOAD_FOLDER = 'static/student_images'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Mở webcam
camera = cv2.VideoCapture(0)

def load_known_faces():
    known_faces = []
    for student in students_collection.find():
        image_path = os.path.join(UPLOAD_FOLDER, student['image_path'])
        if os.path.exists(image_path):
            # Đọc ảnh và chuyển sang RGB (face_recognition yêu cầu RGB)
            image = face_recognition.load_image_file(image_path)
            
            # Tìm khuôn mặt trong ảnh
            face_locations = face_recognition.face_locations(image)
            if len(face_locations) > 0:
                # Lấy encoding của khuôn mặt đầu tiên
                face_encoding = face_recognition.face_encodings(image, face_locations)[0]
                # Thêm thông tin sinh viên và encoding vào danh sách
                known_faces.append({
                    'encoding': face_encoding,
                    'name': student['name'],
                    'student_id': student['student_id']
                })
    return known_faces

def generate_frames():
    known_faces = load_known_faces()
    last_attendance = {}  # Lưu thời gian điểm danh gần nhất của mỗi sinh viên
    frame_count = 0  # Đếm số frame
    process_every_n_frames = 30  # Xử lý mỗi 1 giây (30 FPS)
    last_face_locations = []  # Lưu vị trí khuôn mặt lần nhận diện gần nhất
    last_face_names = []  # Lưu tên người được nhận diện gần nhất
    
    while True:
        success, frame = camera.read()
        if not success:
            break

        frame_count += 1
        
        # Chỉ xử lý nhận diện mỗi N frame
        if frame_count % process_every_n_frames == 0:
            # Chuyển sang RGB cho face_recognition
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # Tìm khuôn mặt trong frame
            face_locations = face_recognition.face_locations(rgb_frame)
            face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)
            
            # Reset danh sách tên
            last_face_names = []
            
            for face_encoding in face_encodings:
                # So sánh với các khuôn mặt đã biết
                recognized = False
                for known_face in known_faces:
                    # So sánh khuôn mặt với ngưỡng 0.6 (càng thấp càng nghiêm ngặt)
                    matches = face_recognition.compare_faces([known_face['encoding']], face_encoding, tolerance=0.6)
                    if matches[0]:
                        recognized = True
                        name = known_face['name']
                        student_id = known_face['student_id']
                        
                        # Kiểm tra xem đã điểm danh chưa
                        now = datetime.now()
                        today = now.strftime("%Y-%m-%d")
                        
                        if student_id not in last_attendance or last_attendance[student_id] != today:
                            # Kiểm tra trong database
                            existing_attendance = attendance_collection.find_one({
                                'student_id': student_id,
                                'date': today
                            })
                            
                            if not existing_attendance:
                                # Ghi log điểm danh
                                attendance_record = {
                                    'student_id': student_id,
                                    'name': name,
                                    'timestamp': now,
                                    'date': today
                                }
                                attendance_collection.insert_one(attendance_record)
                                print(f"{name} ({student_id}) có mặt lúc {now}")
                                last_attendance[student_id] = today
                        
                        last_face_names.append(f"{name} ({student_id})")
                        break
                
                if not recognized:
                    last_face_names.append("Unknown")
            
            # Cập nhật vị trí khuôn mặt mới nhất
            last_face_locations = face_locations

        # Vẽ khung và tên cho tất cả các khuôn mặt đã phát hiện
        for (top, right, bottom, left), name in zip(last_face_locations, last_face_names):
            if name == "Unknown":
                # Vẽ khung cho khuôn mặt không nhận diện được
                cv2.rectangle(frame, (left, top), (right, bottom), (0, 0, 255), 2)
                cv2.putText(frame, name, (left, top-10), 
                          cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            else:
                # Vẽ khung và tên cho khuôn mặt đã nhận diện
                cv2.rectangle(frame, (left, top), (right, bottom), (0, 255, 0), 2)
                cv2.putText(frame, name, (left, top-10), 
                          cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

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

@app.route('/attendance')
def attendance():
    filter_type = request.args.get('filter_type', 'student')
    selected_student = request.args.get('student_id', '')
    selected_date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    
    # Lấy danh sách sinh viên cho dropdown
    students_list = list(students_collection.find())
    
    # Lấy tổng số sinh viên
    total_students = students_collection.count_documents({})
    
    # Xây dựng query dựa trên filter
    query = {}
    if filter_type == 'student' and selected_student:
        query['student_id'] = selected_student
    elif filter_type == 'date':
        query['date'] = selected_date
    
    # Lấy lịch sử điểm danh
    attendance_records = list(attendance_collection.find(query).sort('timestamp', -1))
    
    return render_template('attendance.html',
                         filter_type=filter_type,
                         selected_student=selected_student,
                         selected_date=selected_date,
                         students=students_list,
                         attendance_records=attendance_records,
                         total_students=total_students)

@app.route('/add_student', methods=['POST'])
def add_student():
    image_source = request.form.get('image_source')
    student_id = request.form['student_id']
    student_name = request.form['student_name']
    
    # Kiểm tra xem mã sinh viên đã tồn tại chưa
    if students_collection.find_one({'student_id': student_id}):
        flash('Mã sinh viên đã tồn tại')
        return redirect(url_for('index'))

    try:
        if image_source == 'upload':
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
                image_path = filename

        else:  # webcam
            webcam_image = request.form.get('webcam_image')
            if not webcam_image:
                flash('Vui lòng chụp ảnh trước khi thêm sinh viên')
                return redirect(url_for('index'))

            # Xử lý ảnh base64 từ webcam
            image_data = webcam_image.split(',')[1]
            image_bytes = base64.b64decode(image_data)
            
            # Lưu ảnh
            filename = f"{student_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            with open(file_path, 'wb') as f:
                f.write(image_bytes)
            image_path = filename

        # Thêm sinh viên vào database
        student = {
            'student_id': student_id,
            'name': student_name,
            'image_path': image_path
        }
        
        students_collection.insert_one(student)
        flash('Thêm sinh viên thành công')
        return redirect(url_for('students'))

    except Exception as e:
        flash(f'Có lỗi xảy ra: {str(e)}')
        return redirect(url_for('index'))

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

@app.route('/delete_attendance/<attendance_id>', methods=['POST'])
def delete_attendance(attendance_id):
    try:
        # Chuyển đổi attendance_id thành ObjectId
        attendance_id = ObjectId(attendance_id)
        # Xóa bản ghi điểm danh
        result = attendance_collection.delete_one({'_id': attendance_id})
        if result.deleted_count > 0:
            flash('Xóa lịch sử điểm danh thành công')
        else:
            flash('Không tìm thấy bản ghi điểm danh')
    except Exception as e:
        flash(f'Có lỗi xảy ra khi xóa: {str(e)}')
    return redirect(url_for('attendance'))

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/edit_student/<student_id>', methods=['GET', 'POST'])
def edit_student(student_id):
    student = students_collection.find_one({'student_id': student_id})
    if not student:
        flash('Không tìm thấy sinh viên')
        return redirect(url_for('students'))

    if request.method == 'POST':
        try:
            student_name = request.form['student_name']
            image_source = request.form.get('image_source')
            
            update_data = {'name': student_name}
            
            if image_source == 'upload' and 'student_image' in request.files:
                file = request.files['student_image']
                if file.filename != '':
                    # Xóa ảnh cũ
                    old_image_path = os.path.join(UPLOAD_FOLDER, student['image_path'])
                    if os.path.exists(old_image_path):
                        os.remove(old_image_path)
                    
                    # Lưu ảnh mới
                    filename = secure_filename(file.filename)
                    file_path = os.path.join(UPLOAD_FOLDER, filename)
                    file.save(file_path)
                    update_data['image_path'] = filename
                    
            elif image_source == 'webcam':
                webcam_image = request.form.get('webcam_image')
                if webcam_image:
                    # Xóa ảnh cũ
                    old_image_path = os.path.join(UPLOAD_FOLDER, student['image_path'])
                    if os.path.exists(old_image_path):
                        os.remove(old_image_path)
                    
                    # Lưu ảnh mới từ webcam
                    image_data = webcam_image.split(',')[1]
                    image_bytes = base64.b64decode(image_data)
                    filename = f"{student_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                    file_path = os.path.join(UPLOAD_FOLDER, filename)
                    with open(file_path, 'wb') as f:
                        f.write(image_bytes)
                    update_data['image_path'] = filename
            
            # Cập nhật thông tin sinh viên
            students_collection.update_one(
                {'student_id': student_id},
                {'$set': update_data}
            )
            
            flash('Cập nhật thông tin sinh viên thành công')
            return redirect(url_for('students'))
            
        except Exception as e:
            flash(f'Có lỗi xảy ra: {str(e)}')
    
    return render_template('edit_student.html', student=student)

if __name__ == "__main__":
    try:
        # Kiểm tra camera
        if not camera.isOpened():
            print("Không thể mở camera. Vui lòng kiểm tra kết nối camera.")
            exit(1)
            
        # Chạy Flask trên port 5001
        app.run(debug=True, port=5001)
    except Exception as e:
        print(f"Có lỗi xảy ra: {str(e)}")
    finally:
        # Đóng camera khi thoát
        camera.release()