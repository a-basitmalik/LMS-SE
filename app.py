import mysql.connector
from flask import Flask, render_template, request, jsonify, redirect, session, url_for,flash
from datetime import datetime, timedelta
import pytz
import pandas as pd
from flask import send_file
from io import BytesIO
import io
from functools import wraps
import json
from collections import defaultdict
import os
from werkzeug.utils import secure_filename


DB_CONFIG = {
    'host': '127.0.0.1',
    'user': 'rfid',
    'password': 'TRY/One12',
    'database': 'rfid',
    'port': 3306,  # Default MySQL port
    'charset': 'utf8mb4',  # Ensure charset is set to utf8mb4 for full Unicode support
    'ssl_disabled': True,  # SSL is not being used
}




class Database:
    def __init__(self, config):
        self.config = config

    def fetch_absentees(self):
        query = """
           SELECT s.RFID, s.student_name, s.AbsenteeID
           FROM Students s
           JOIN General_Attendance ga ON s.RFID = ga.RFID
           WHERE ga.Status = 'Absent'
           """
        return self.fetch_data(query)

    def connect(self):
        return mysql.connector.connect(**self.config)

    def fetch_data(self, query, params=None):
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute(query, params)
            data = cursor.fetchall()
            cursor.close()
            conn.close()
            return data
        except mysql.connector.Error as e:
            print("MySQL Error:", e)
            return []

    def execute_query(self, query, params=None):
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()
            cursor.close()
            conn.close()
        except mysql.connector.Error as e:
            print("MySQL Error:", e)


class RFIDHandler:
    def __init__(self, db):
        self.db = db

    def check_rfid_exists(self, rfid):
        # First, check in the Students table
        result = self.db.fetch_data("SELECT * FROM Students WHERE RFID = %s", (rfid,))
        print("Students table result:", result)

        if len(result) > 0:
            return rfid  # Return the full record from Students table if found

        # If not found, check in the Alternative_Rfid table
        alternative_result = self.db.fetch_data("SELECT rfid FROM Alternative_Rfid WHERE Card_Rfid = %s", (rfid,))

        if len(alternative_result) > 0:
            # Extract the corresponding rfid from Alternative_Rfid
            return alternative_result[0][0]
            print("Alternative RFID found:", alternative_rfid)

            # Now retrieve the full record from the Students table using the alternative rfid
            result_from_students = self.db.fetch_data("SELECT * FROM Students WHERE RFID = %s", (alternative_rfid,))
            print("Students table result from alternative RFID:", result_from_students)

            if len(result_from_students) > 0:
                return result_from_students[0]  # Return the full record from Students table

        return None  # Return None if not found in either table


    def check_employee_exists(self, rfid):
        result = self.db.fetch_data("SELECT * FROM employee WHERE RFID = %s", (rfid,))
        return len(result) > 0

    def check_general_attendance_exists(self, rfid, date):
    	
        result = self.db.fetch_data("SELECT * FROM General_Attendance WHERE RFID = %s AND date = %s", (rfid, date))
        return len(result) > 0

    def check_subject_attendance_exists(self, rfid, subject_id, date):
        result = self.db.fetch_data("SELECT * FROM Subject_Attendance WHERE RFID = %s AND subject_id = %s "
                                    "AND date = %s", (rfid, subject_id, date))
        return len(result) > 0

    def mark_general_attendance(self, rfid, date_time):
        try:
            if self.check_rfid_exists(rfid):
            
            	
                date_time_obj = datetime.strptime(date_time, '%Y-%m-%d %H:%M:%S')
                rfid=self.check_rfid_exists(rfid)
                if not self.check_general_attendance_exists(rfid, date_time_obj.date()):
                    self.db.execute_query(
                        "INSERT INTO General_Attendance (RFID, date, time,status) VALUES (%s, %s, %s,%s)",
                        (rfid, date_time_obj.date(), date_time_obj.time(), 'Present')
                    )
                    self.db.execute_query(
                        "UPDATE Students SET DaysAttended = DaysAttended + 1 WHERE RFID = %s", (rfid,)
                    )
                    self.db.execute_query(
                        "UPDATE Students SET TotalDays = TotalDays + 1 WHERE RFID = %s", (rfid,)
                    )
                    print("General attendance marked and DaysAttended incremented successfully!")
                else:
                    print("General attendance already marked for today.")
            else:
                print("RFID does not exist in the student table.")
        except mysql.connector.Error as e:
            print("MySQL Error:", e)

    def mark_subject_attendance(self, rfid, date_time):
        try:
            if self.check_rfid_exists(rfid):
                date_time_obj = datetime.strptime(date_time, '%Y-%m-%d %H:%M:%S')
                current_day = date_time_obj.strftime('%A')
                

                enrolled_subject = self.db.fetch_data(
                    "SELECT se.subject_id, su.time, su.day FROM Subjects_Enrolled se "
                    "JOIN Subjects su ON se.subject_id = su.subject_id "
                    "WHERE se.RFID = %s AND su.day = %s", (rfid, current_day)
                )

                if enrolled_subject:
                    subject_id, subject_time, subject_day = enrolled_subject[0]

                    # Check if subject_time is None
                    if subject_time is None:
                        print(f"Subject time for subject ID {subject_id} is None.")
                        return

                    subject_time_obj = datetime.strptime(str(subject_time), '%H:%M:%S').time()
                    subject_datetime = datetime.combine(date_time_obj.date(), subject_time_obj)

                    if abs((date_time_obj - subject_datetime).total_seconds()) <= 40 * 60:
                        if not self.check_subject_attendance_exists(rfid, subject_id, date_time_obj.date()):
                            self.db.execute_query(
                                "INSERT INTO Subject_Attendance (RFID, subject_id, attendance_status, date, time)"
                                " VALUES (%s, %s, 'Present', %s, %s)",
                                (rfid, subject_id, date_time_obj.date(), date_time_obj.time())
                            )
                            self.db.execute_query(
                                "UPDATE Subjects_Enrolled SET SubjectAttended"
                                " = SubjectAttended + 1 WHERE RFID = %s AND subject_id = %s",
                                (rfid, subject_id)
                            )
                            self.db.execute_query(
                                "UPDATE Subjects_Enrolled SET TotalDays ="
                                " TotalDays + 1 WHERE RFID = %s AND subject_id = %s",
                                (rfid, subject_id)
                            )
                            print(
                                f"Subject attendance marked and SubjectAttended incremented "
                                f"successfully for subject ID {subject_id} on {subject_day}!")
                        else:
                            print(f"Subject attendance already marked for subject ID {subject_id} today.")
                    else:
                        print("Attendance marking time window exceeded.")
                else:
                    print("No subject found for the current day and time.")
            else:
                print("RFID does not exist in the student table.")
        except mysql.connector.Error as e:
            print("MySQL Error:", e)

    def mark_absent_general_attendance(self, date):
        try:
            students = self.db.fetch_data("SELECT RFID FROM Students")
            date_time_obj = datetime.strptime(date, '%Y-%m-%d %H:%M:%S')
            for student in students:
                rfid = student[0]

                if not self.check_general_attendance_exists(rfid, date_time_obj.date()):
                    self.db.execute_query(
                        "INSERT INTO General_Attendance (RFID, date, time,status) VALUES (%s, %s, %s,%s)",
                        (rfid, date_time_obj.date(), date_time_obj.time(), 'Absent')
                    )
                    self.db.execute_query(
                        "UPDATE Students SET TotalDays = TotalDays + 1, Fine= Fine+100 WHERE RFID = %s", (rfid,)
                    )
                    print(f"Marked general attendance as 'Absent' for RFID {rfid} on {date}.")
        except mysql.connector.Error as e:
            print("MySQL Error:", e)

    def mark_absent_subject_attendance(self, date):
        try:
            date_time_obj = datetime.strptime(date, '%Y-%m-%d %H:%M:%S')
            subjects = self.db.fetch_data(
                "SELECT RFID, subject_id FROM Subjects_Enrolled "
                "WHERE subject_id IN (SELECT subject_id FROM Subjects WHERE day = %s)",
                (date_time_obj.strftime('%A'),)
            )
            for subject in subjects:
                rfid, subject_id = subject
                if not self.check_subject_attendance_exists(rfid, subject_id, date_time_obj.date()):
                    self.db.execute_query(
                        "INSERT INTO Subject_Attendance "
                        "(RFID, subject_id, attendance_status, date, time) VALUES (%s, %s, 'Absent', %s, %s)",
                        (rfid, subject_id, date_time_obj.date(), date_time_obj.time())
                    )
                    self.db.execute_query(
                        "UPDATE Subjects_Enrolled SET TotalDays = TotalDays + 1 WHERE RFID = %s AND subject_id = %s",
                        (rfid, subject_id)
                    )
                    print(
                        f"Marked subject attendance as 'Absent' for RFID {rfid} and subject ID {subject_id} on {date}.")
        except mysql.connector.Error as e:
            print("MySQL Error:", e)

    def find_bunks(self):
        try:
            current_date = datetime.now().date()
            current_day = datetime.now().strftime('%A')  # Get the current day of the week
            students = self.db.fetch_data("SELECT RFID FROM Students")

            for student in students:
                rfid = student[0]
                general_attendance_today = self.db.fetch_data(
                    "SELECT * FROM General_Attendance WHERE RFID = %s AND date = %s", (rfid, current_date)
                )

                if general_attendance_today:
                    enrolled_subjects = self.db.fetch_data(
                        "SELECT se.subject_id, su.time, su.day FROM Subjects_Enrolled se "
                        "JOIN Subjects su ON se.subject_id = su.subject_id "
                        "WHERE se.RFID = %s AND su.day = %s", (rfid, current_day)
                    )

                    for subject in enrolled_subjects:
                        subject_id, subject_time, subject_day = subject
                        subject_time_obj = datetime.strptime(str(subject_time), '%H:%M:%S').time()
                        subject_datetime = datetime.combine(current_date, subject_time_obj)
                        current_time = datetime.now()

                        if current_time > subject_datetime + timedelta(minutes=40):
                            # Check if bunk record already exists
                            existing_bunk = self.db.fetch_data(
                                "SELECT * FROM Bunk WHERE RFID = %s AND subject_id = %s AND date = %s",
                                (rfid, subject_id, current_date)
                            )

                            if not existing_bunk:
                                # Mark as bunked
                                self.db.execute_query(
                                    "INSERT INTO Bunk (RFID, subject_id, date) VALUES (%s, %s, %s)",
                                    (rfid, subject_id, current_date)
                                )
                                print(f"Student with RFID {rfid} bunked subject {subject_id} on {current_date}.")
                            else:
                                print(
                                    f"Bunk record already exists for student with RFID {rfid} for subject {subject_id}"
                                    f" on {current_date}.")
        except mysql.connector.Error as e:
            print("MySQL Error:", e)

    def mark_employee_check_in(self, rfid, check_in_time):
        try:
            if self.check_employee_exists(rfid):
                check_in_time_obj = datetime.strptime(check_in_time, '%Y-%m-%d %H:%M:%S')
                date = check_in_time_obj.date()
                existing_record = self.db.fetch_data(
                    "SELECT * FROM Employee_Attendance WHERE RFID = %s AND Attendance_date = %s", (rfid, date)
                )

                if not existing_record:
                    self.db.execute_query(
                        "INSERT INTO Employee_Attendance"
                        " (RFID, employee_check_in, Attendance_date, Attendance_status) VALUES (%s, %s, %s, 'Present')",
                        (rfid, check_in_time_obj.time(), date)
                    )
                    self.db.execute_query(
                        "UPDATE employee SET Days_Attended = Days_Attended + 1 WHERE RFID = %s", (rfid,)
                    )
                    self.db.execute_query(
                        "UPDATE employee SET Total_Days = Total_Days + 1 WHERE RFID = %s", (rfid,)
                    )

                    if check_in_time_obj.time() > datetime.strptime('08:00:00', '%H:%M:%S').time():
                        self.db.execute_query(
                            "UPDATE employee SET LateDays = LateDays + 1 WHERE RFID = %s", (rfid,)
                        )

                    print(f"Employee check-in marked for RFID {rfid} at {check_in_time}.")
                else:
                    print("Check-in already marked for today.")
            else:
                print("RFID does not exist in the employee table.")
        except mysql.connector.Error as e:
            print("MySQL Error:", e)

    def mark_employee_check_out(self, rfid, check_out_time):
        try:
            if self.check_employee_exists(rfid):
                check_out_time_obj = datetime.strptime(check_out_time, '%Y-%m-%d %H:%M:%S')
                date = check_out_time_obj.date()

                existing_record = self.db.fetch_data(
                    "SELECT employee_check_in FROM Employee_Attendance WHERE RFID = %s AND Attendance_date = %s",
                    (rfid, date)
                )

                if existing_record:
                    check_in_time = existing_record[0][0]

                    if isinstance(check_in_time, timedelta):
                        # Convert timedelta to time object
                        check_in_time = (datetime.min + check_in_time).time()
                    elif isinstance(check_in_time, datetime):
                        # Extract time part if it is a datetime object
                        check_in_time = check_in_time.time()

                    check_in_time_obj = datetime.combine(date, check_in_time)

                    if (check_out_time_obj - check_in_time_obj).total_seconds() >= 40 * 60:
                        self.db.execute_query(
                            "UPDATE Employee_Attendance SET employee_check_out = %s WHERE RFID = %s AND Attendance_date = %s",
                            (check_out_time_obj.time(), rfid, date)
                        )
                        print(f"Employee check-out marked for RFID {rfid} at {check_out_time}.")
                    else:
                        print("Check-out time is less than 40 minutes from check-in time.")
                else:
                    print("No check-in record found for today.")
            else:
                print("RFID does not exist in the employee table.")
        except mysql.connector.Error as e:
            print("MySQL Error:", e)

    def mark_absent_employee_attendance(self, date):
        try:
            employees = self.db.fetch_data("SELECT RFID FROM employee")
            date_time_obj = datetime.strptime(date, '%Y-%m-%d %H:%M:%S')

            # Mark absent for employees
            for employee in employees:
                rfid = employee[0]
                if not self.check_employee_attendance_exists(rfid, date_time_obj.date()):
                    self.db.execute_query(
                        "INSERT INTO Employee_Attendance (RFID, Attendance_date, Attendance_status) VALUES (%s, %s, 'Absent')",
                        (rfid, date_time_obj.date())
                    )
                    self.db.execute_query(
                        "UPDATE employee SET Total_Days = Total_Days + 1 WHERE RFID = %s", (rfid,)
                    )
                    print(f"Marked employee attendance as 'Absent' for RFID {rfid} on {date}.")
        except mysql.connector.Error as e:
            print("MySQL Error:", e)

    def check_employee_attendance_exists(self, rfid, date):
        result = self.db.fetch_data("SELECT * FROM Employee_Attendance WHERE RFID = %s AND Attendance_date = %s",
                                    (rfid, date))
        return len(result) > 0

class AppRoutes:

    def __init__(self, app, db):
        self.app = app
        self.db = db
        self.rfid_handler = RFIDHandler(db)
        self.setup_routes()

    def setup_routes(self):
        app.secret_key = 'a.basit1'
        UPLOAD_FOLDER = 'static/images'
        self.app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
        self.app.route('/attendance', methods=['GET'])(self.attendance)
        self.app.route('/students', methods=['GET'])(self.students)
        self.app.route('/search_students', methods=['GET'])(self.search_students)
        self.app.route('/employees', methods=['GET'])(self.employees)
        self.app.route('/search_employees', methods=['GET'])(self.search_employees)
        self.app.route('/subjects', methods=['GET'])(self.subjects)
        self.app.route('/general_attendance', methods=['GET'])(self.general_attendance)
        self.app.route('/search_general_attendance', methods=['GET'])(self.search_general_attendance)
        self.app.route('/subject_attendance', methods=['GET'])(self.subject_attendance)
        self.app.route('/search_subject_attendance')(self.search_subject_attendance)
        self.app.route('/submit_rfid', methods=['POST'])(self.submit_rfid)
        self.app.route('/submit_subject_rfid', methods=['POST'])(self.submit_subject_rfid)
        self.app.route('/bunk', methods=['GET'])(self.bunk)
        self.app.route('/get_bunks', methods=['GET'])(self.get_bunks)
        self.app.route('/search_bunks', methods=['GET'])(self.search_bunks)
        self.app.route('/index')(self.index)
        self.app.route('/student_details/<rfid>', methods=['GET'])(self.student_details)
        self.app.route('/employee_details/<rfid>', methods=['GET'])(self.employee_details)
        self.app.route('/submit_general_attendance', methods=['POST'])(self.submit_general_attendance)
        self.app.route('/mark_general_attendance', methods=['GET'])(self.mark_general_attendance)
        self.app.route('/student_details2/<rfid>', methods=['GET'])(self.student_details2)
        self.app.route('/submit_subject_attendance', methods=['POST'])(self.submit_subject_attendance)
        self.app.route('/mark_subject_attendance', methods=['GET'])(self.mark_subject_attendance)
        #self.app.route('/login', methods=['GET', 'POST'])(self.login)
        self.app.route('/student_dashboard')(self.student_dashboard)
        self.app.route('/update_attendance/<int:rfid>', methods=['POST'])(self.update_attendance)
        self.app.route('/subject_attendance/<rfid>/<subject_id>', methods=['GET'])(self.subject_attendance_page)
        self.app.route('/general_attendance/<rfid>', methods=['GET'])(self.general_attendance_page)
        self.app.route('/register_student', methods=['GET', 'POST'])(self.register_student)
        self.app.route('/register_students', methods=['GET'])(self.register_students)
        self.app.route('/enroll_subjects', methods=['GET', 'POST'])(self.enroll_subjects)
        self.app.route('/Enroll', methods=['GET'])(self.Enroll)
        self.app.route('/subject_students/<int:subject_id>')(self.subject_students)
        self.app.route('/export_bunks')(self.export_bunks)
        self.app.route('/export_general_attendance')(self.export_general_attendance)
        self.app.route('/export_subject_attendance', methods=['GET'])(self.export_subject_attendance_to_excel)
        self.app.route('/view_quiz_marks/<int:quiz_id>', methods=['GET'])(self.view_quiz_marks)
        self.app.route('/subjects/<rfid>')(self.student_subjects)
        self.app.route('/mark_subject_2attendance/<subject_id>', methods=['POST', 'GET'])(self.mark_subject_2attendance)
        self.app.route('/subject_records/<subject_id>')(self.subject_records)
        self.app.route('/view_attendance/<rfid>/<subject_id>')(self.view_attendance)
        self.app.route('/view_all_students')(self.view_all_students)
        self.app.route('/todays_subjects')(self.todays_subjects)
        self.app.route('/absentees_list', methods=['GET', 'POST'])(self.absentees_list)
        self.app.route('/export_to_excel', methods=['POST'])(self.export_to_excel)
        self.app.route('/logout')(self.logout)
        self.app.route('/', methods=['GET', 'POST'])(self.login)
        #self.app.route('/student_dashboard')(self.student_dashboard)
        self.app.route('/logout')(self.logout)
        self.app.route('/teacher_dashboard')(self.teacher_dashboard)
        self.app.route('/campus_admin_dashboard')(self.campus_admin_dashboard)
        self.app.route('/make_assessment', methods=['GET', 'POST'])(self.make_assessment)
        #self.app.route('/mark_subject_attendance', methods=['GET', 'POST'])(self.mark_subject_attendance)
        self.app.route('/unmarked_assessments')(self.unmarked_assessments)
        self.app.route('/unmarked_quizzes')(self.unmarked_quizzes)
        self.app.route('/marked_assessments')(self.marked_assessments)
        self.app.route('/campus/<int:campus_id>/attendance_students')(self.attendance_students)
        
        self.app.route('/submission_success')(self.submission_success)
        
        self.app.route('/campus/<int:campus_id>/attendance_students')(self.attendance_students)
        self.app.route('/campus/<int:campus_id>/upload_exam', methods=['GET', 'POST'])(self.upload_exam)
        self.app.route('/exam_submission/<int:exam_id>', methods=['GET', 'POST'])(self.exam_submission)
        self.app.route('/submit_solution/<exam_id>', methods=['POST'])(self.submit_solution)
        
        self.app.route('/campus/<int:campus_id>/Student_Subjects_Enrollment')(self.Student_Subjects_Enrollment)
        self.app.route('/campus/<int:campus_id>/view_students')(self.view_students)
        
        self.app.route('/campus/<int:campus_id>/attendance_employees')(self.attendance_employees)
        self.app.route('/subject/<int:subject_id>/view_submissions')(self.view_submissions)
        self.app.route('/update_all_attendance', methods=['POST'])(self.update_all_attendance)
       
       # self.app.route('/subject_attendance/<rfid>/<subject_id>')(self.subject_attendance_page)
       # self.app.route('/todays_subjects')(self.todays_subjects)
        self.app.route('/enter_marks/<int:assessment_id>', methods=['GET', 'POST'])(self.enter_marks)
        self.app.route('/enter_quiz_marks/<int:quiz_id>', methods=['GET', 'POST'])(self.enter_quiz_marks)
        self.app.route('/assessment_details/<assessment_type>', methods=['GET'])(self.assessment_details)
        self.app.route('/view_marks/<int:assessment_id>', methods=['GET'])(self.view_marks)
        self.app.route('/marked_quizzes')(self.marked_quizzes)
        self.app.route('/campus/<int:campus_id>/subjects')(self.campus_subjects)
        self.app.route('/subject/<int:subject_id>/assessment')(self.view_assessment_details)
       # self.app.route('/view_quiz_marks/<int:quiz_id>', methods=['GET'])(self.view_quiz_marks)
        self.app.route('/subject/<int:subject_id>/monthly-assessment')(self.view_monthly_assessment_details)
        self.app.route('/subject/<int:subject_id>/attendance')(self.view_attendance_records)
        self.app.route('/campus/<int:campus_id>/students')(self.view_all_2students)
        self.app.route('/update_marks', methods=['POST'])(self.update_marks)
        self.app.route('/update_2marks', methods=['POST'])(self.update_2marks)
        self.app.route('/enroll_into_subjects', methods=['GET', 'POST'])(self.enroll_into_subjects)
        self.app.route('/update_absentee', methods=['GET', 'POST'])(self.update_absentee)
        self.app.route('/upload_picture', methods=['GET', 'POST'])(self.upload_picture)
        self.app.route('/campus/<int:campus_id>/result_students')(self.result_students)
        self.app.route('/view_student_assessment_details/<int:student_id>', methods=['GET'])(self.view_student_assessment_details)
        self.app.route('/view_student_assessment_details/<int:student_id>', methods=['GET'])(self.view_student_assessment_details)
        self.app.route('/view_student_assessment_details_send_up/<int:student_id>', methods=['GET'])(self.view_student_assessment_details_send_up)        
        self.app.route('/campus/<int:campus_id>/list_and_update_fees', methods=['GET', 'POST'])(self.list_and_update_fees)
        self.app.route('/campus/<int:campus_id>/update_student_fees', methods=['GET', 'POST'])(self.update_student_fees)
        self.app.route('/campus/<int:campus_id>/list_and_update_fine', methods=['GET', 'POST'])(self.list_and_update_fine)
        self.app.route('/campus/<int:campus_id>/update_student_fines', methods=['GET', 'POST'])(self.update_student_fines)
        self.app.route('/student_subjects2/<int:rfid>', methods=['GET'])(self.student_subjects2)
        self.app.route('/enroll_subject/<int:rfid>/<int:subject_id>', methods=['POST'])(self.enroll_subject)
        self.app.route('/unenroll_subject/<int:rfid>/<int:subject_id>', methods=['POST'])(self.unenroll_subject)
        self.app.route('/syllabus_and_schedules')(self.syllabus_and_schedules)

        

    def login_required(self, role=None):
        def decorator(f):
            @wraps(f)
            def decorated_function(*args, **kwargs):
                if 'username' not in session:
                    return redirect(url_for('login'))
                if role and session.get('role') != role:
                    return redirect(url_for('login'))
                return f(*args, **kwargs)

            return decorated_function

        return decorator

    def authenticate_user(self, username, password):
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)

        # Check Admin table
        cursor.execute("SELECT * FROM Admin WHERE username = %s AND password = %s", (username, password))
        admin = cursor.fetchone()
        if admin:
            cursor.close()
            conn.close()
            return 'admin'

        # Check Teachers table
        cursor.execute("SELECT * FROM Teachers WHERE teacherid = %s AND password = %s", (username, password))
        teacher = cursor.fetchone()
        if teacher:
            cursor.close()
            conn.close()
            return 'teacher'

        # Check Students table
        cursor.execute("SELECT * FROM Students WHERE rfid = %s AND password = %s", (username, password))
        student = cursor.fetchone()
        if student:
            cursor.close()
            conn.close()
            return 'student'

        # Check CampusAdmin table
        cursor.execute("SELECT * FROM CampusAdmin WHERE username = %s AND password = %s", (username, password))
        campus_admin = cursor.fetchone()
        if campus_admin:
            cursor.close()
            conn.close()
            return 'campus_admin'

        cursor.close()
        conn.close()
        return None

    def login(self):
        if request.method == 'POST':
            username = request.form['username']
            password = request.form['password']

            role = self.authenticate_user(username, password)
            if role == 'student':
                conn = mysql.connector.connect(**DB_CONFIG)
                cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT RFID FROM Students WHERE RFID = %s AND password = %s", (username, password))
                student = cursor.fetchone()
                if student:
                    session['rfid'] = student['RFID']
                    session['username'] = username
                    session['role'] = role
                    cursor.close()
                    conn.close()
                    return redirect(url_for('student_dashboard'))
                cursor.close()
                conn.close()

            if role == 'admin':
                session['username'] = username
                session['role'] = role
                return redirect(url_for('index'))

            if role == 'teacher':
                session['username'] = username
                session['role'] = role
                return redirect(url_for('teacher_dashboard'))

            if role == 'campus_admin':
                conn = mysql.connector.connect(**DB_CONFIG)
                cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT campusid FROM CampusAdmin WHERE username = %s AND password = %s",
                               (username, password))
                campus_admin = cursor.fetchone()
                if campus_admin:
                    session['username'] = username
                    session['role'] = role
                    session['campus_id'] = campus_admin['campusid']
                    cursor.close()
                    conn.close()
                    return redirect(url_for('campus_admin_dashboard'))
                cursor.close()
                conn.close()

            return 'Invalid credentials', 401

        return render_template('login.html')

    def logout(self):
        session.pop('username', None)
        session.pop('role', None)
        return redirect(url_for('login'))


    @login_required('campus_admin')
    def campus_admin_dashboard(self):
        campus_id = session.get('campus_id')
        if not campus_id:
            return 'Unauthorized', 403

        conn = self.get_db_connection()
        cursor = conn.cursor()

        query = '''
            SELECT c.CampusID, c.CampusName, COUNT(s.StudentID) as TotalStudents
            FROM Campus c
            LEFT JOIN Students s ON c.CampusID = s.campusid
            WHERE c.CampusID = %s
            GROUP BY c.CampusID, c.CampusName
        '''
        cursor.execute(query, (campus_id,))
        campuses = cursor.fetchall()
        print(campuses)
        cursor.close()
        conn.close()

        return render_template('campus_admin_dashboard.html', campuses=campuses)
    
    def syllabus_and_schedules(self):
        return render_template('syllabus_and_schedules.html')
        
    @login_required('admin')
    def view_student_assessment_details(self,student_id):
        # Default to 'Monthly' assessment type
        assessment_type = 'Monthly'

        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Fetch monthly assessments for the given student
        cursor.execute("""
            SELECT a.assessment_id, a.subject_id, a.total_marks, am.Marks_Acheived AS monthly_marks_achieved, a.sequence, s.subject_name, a.created_at
            FROM Assessments a
            JOIN assessments_marks am ON a.assessment_id = am.assessment_id
            JOIN Subjects s ON a.subject_id = s.subject_id
            WHERE a.assessment_type = %s AND am.rfid = %s
            ORDER BY a.subject_id, a.created_at
        """, (assessment_type, student_id))
        assessments = cursor.fetchall()

        # Fetch quizzes and quiz marks for the given student
        cursor.execute("""
            SELECT q.quiz_id, q.monthly_assessment_id, q.quiz_number, qm.marks_achieved, q.created_at, a.subject_id
            FROM quizzes q
            JOIN quiz_marks qm ON q.quiz_id = qm.quiz_id
            JOIN Assessments a ON q.monthly_assessment_id = a.assessment_id
            WHERE a.assessment_type = %s AND qm.rfid = %s
            ORDER BY q.monthly_assessment_id, q.quiz_number
        """, (assessment_type, student_id))
        quizzes = cursor.fetchall()

        cursor.close()
        conn.close()

        # Process data (similar to the original function)
        processed_assessments = {}
        for assessment in assessments:
            subject_id = assessment['subject_id']
            assessment_date = assessment['created_at']
            year_month = assessment_date.strftime('%Y-%m')

            if year_month not in processed_assessments:
                processed_assessments[year_month] = {
                    'MonthYear': assessment_date.strftime('%B %Y'),
                    'Records': []
                }

            if subject_id not in [record['subject_id'] for record in processed_assessments[year_month]['Records']]:
                processed_assessments[year_month]['Records'].append({
                    'subject_name': assessment['subject_name'],
                    'MonthlyMarks_Achieved': 'NA',
                    'QuizMarks': {
                        'Quiz1': 0,
                        'Quiz2': 0,
                        'Quiz3': 0
                    },
                    'TotalMarks': 35,
                    'QuizTotalMarks': 15,
                    'TotalMarks_Achieved': 0,
                    'Grade': 'NA',
                    'subject_id': subject_id
                })

            if assessment['sequence'] >= 100:  # Monthly assessment
                for record in processed_assessments[year_month]['Records']:
                    if record['subject_id'] == subject_id:
                        record['MonthlyMarks_Achieved'] = assessment['monthly_marks_achieved']

        # Link quizzes to assessments
        for quiz in quizzes:
            for month_year, data in processed_assessments.items():
                for record in data['Records']:
                    if record['subject_id'] == quiz['subject_id'] and quiz['created_at'].strftime(
                            '%Y-%m') == month_year:
                        quiz_number = f'Quiz{quiz["quiz_number"]}'
                        record['QuizMarks'][quiz_number] = quiz['marks_achieved']

        # Calculate total marks and grade
        for month_year, data in processed_assessments.items():
            for record in data['Records']:
                quiz_marks = [record['QuizMarks'].get(f'Quiz{i}', 0) for i in range(1, 4)]
                average_quiz_marks = sum(quiz_marks) / len(quiz_marks) if any(quiz_marks) else 0
                record['TotalMarks_Achieved'] = average_quiz_marks + (
                    record['MonthlyMarks_Achieved'] if record['MonthlyMarks_Achieved'] != 'NA' else 0)
                record['Grade'] = self.calculate_grade(
                    record['TotalMarks_Achieved'] / record['TotalMarks'] * 100 if record['TotalMarks'] else 0)

        return render_template('assessment_details.html',
                               assessments=processed_assessments,
                               assessment_type=assessment_type)
    @login_required('admin')
    def view_student_assessment_details_send_up(self,student_id):
        # Default to 'Send Up' assessment type
        assessment_type = 'Send Up'
        if assessment_type not in ['Monthly', 'Class', 'Mid', 'Final', 'Send Up', 'Mocks', 'Finals', 'Others']:
            return redirect(url_for('student_dashboard'))

        # Retrieve RFID from session
        rfid = student_id

        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if assessment_type == 'Monthly':
            # Fetch monthly assessments and their details
            cursor.execute("""
                    SELECT a.assessment_id, a.subject_id, a.total_marks, am.Marks_Acheived AS monthly_marks_achieved, a.sequence, s.subject_name, a.created_at
                    FROM Assessments a
                    JOIN assessments_marks am ON a.assessment_id = am.assessment_id
                    JOIN Subjects s ON a.subject_id = s.subject_id
                    WHERE a.assessment_type = %s AND am.rfid = %s
                    ORDER BY a.subject_id, a.created_at
                """, (assessment_type, rfid))
            assessments = cursor.fetchall()

            # Fetch quizzes and quiz marks
            cursor2 = conn.cursor(dictionary=True)
            cursor2.execute("""
                    SELECT q.quiz_id, q.monthly_assessment_id, q.quiz_number, qm.marks_achieved, q.created_at, a.subject_id
                    FROM quizzes q
                    JOIN quiz_marks qm ON q.quiz_id = qm.quiz_id
                    JOIN Assessments a ON q.monthly_assessment_id = a.assessment_id
                    WHERE a.assessment_type = %s AND qm.rfid = %s
                    ORDER BY q.monthly_assessment_id, q.quiz_number
                """, (assessment_type, rfid))
            quizzes = cursor2.fetchall()
            cursor2.close()
        else:
            cursor.execute("""
                    SELECT a.assessment_id, a.subject_id, a.total_marks, am.Marks_Acheived, a.sequence, s.subject_name, a.created_at
                    FROM Assessments a
                    JOIN assessments_marks am ON a.assessment_id = am.assessment_id
                    JOIN Subjects s ON a.subject_id = s.subject_id
                    WHERE a.assessment_type = %s AND am.rfid = %s
                    ORDER BY a.subject_id
                """, (assessment_type, rfid))
            assessments = cursor.fetchall()
            quizzes = []

        cursor.close()
        conn.close()
        

        # Process data
        processed_assessments = {}
        for assessment in assessments:
            subject_id = assessment['subject_id']
            assessment_date = assessment['created_at']
            year_month = assessment_date.strftime('%Y-%m')  # Format for month and year

            if assessment_type == 'Monthly':
                if year_month not in processed_assessments:
                    processed_assessments[year_month] = {
                        'MonthYear': assessment_date.strftime('%B %Y'),
                        'Records': []
                    }
                if subject_id not in [record['subject_id'] for record in processed_assessments[year_month]['Records']]:
                    processed_assessments[year_month]['Records'].append({
                        'subject_name': assessment['subject_name'],
                        'MonthlyMarks_Achieved': 'NA',
                        'QuizMarks': {
                            'Quiz1': 0,
                            'Quiz2': 0,
                            'Quiz3': 0
                        },
                        'TotalMarks': 35,
                        'QuizTotalMarks': 15,
                        'TotalMarks_Achieved': 0,
                        'Grade': 'NA',
                        'subject_id': subject_id
                    })

                # Handle monthly assessment marks
                if assessment['sequence'] >= 100:  # Monthly assessment
                    for record in processed_assessments[year_month]['Records']:
                        if record['subject_id'] == subject_id:
                            record['MonthlyMarks_Achieved'] = assessment['monthly_marks_achieved']

        # Link quizzes to assessments
        if assessment_type == 'Monthly':
            for quiz in quizzes:
                for month_year, data in processed_assessments.items():
                    # Find the right subject and created_at match for quiz assignment
                    for record in data['Records']:
                        if record['subject_id'] == quiz['subject_id'] and quiz['created_at'].strftime(
                                '%Y-%m') == month_year:
                            quiz_number = f'Quiz{quiz["quiz_number"]}'
                            record['QuizMarks'][quiz_number] = quiz['marks_achieved']

            # Calculate total marks and grade
            for month_year, data in processed_assessments.items():
                for record in data['Records']:
                    quiz_marks = [record['QuizMarks'].get(f'Quiz{i}', 0) for i in range(1, 4)]
                    average_quiz_marks = sum(quiz_marks) / len(quiz_marks) if any(quiz_marks) else 0
                    record['TotalMarks_Achieved'] = average_quiz_marks + (
                        record['MonthlyMarks_Achieved'] if record['MonthlyMarks_Achieved'] != 'NA' else 0)
                    record['Grade'] = self.calculate_grade(
                        record['TotalMarks_Achieved'] / record['TotalMarks'] * 100 if record['TotalMarks'] else 0)

        else:
            for subject_id, data in processed_assessments.items():
                percentage = (data['Marks_Acheived'] / data['total_marks']) * 100 if data['total_marks'] else 0
                data['Grade'] = self.calculate_grade(percentage)
            processed_assessments=assessments

        return render_template('assessment_details.html',
                               assessments=processed_assessments,
                               assessment_type=assessment_type)    

    @login_required('admin')
    def Student_Subjects_Enrollment(self, campus_id):
        campus_id = campus_id
        if not campus_id:
            return 'Unauthorized', 403

        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Query to get all students with their attendance status for today
        query = '''
            SELECT s.rfid, s.Student_Name, ga.Status, s.year
            FROM Students s
            LEFT JOIN General_Attendance ga ON s.RFID = ga.RFID AND ga.date = CURDATE()
            WHERE s.campusid = %s
            Order by s.year  
        '''
        cursor.execute(query, (campus_id,))
        students = cursor.fetchall()

        # Summary counts for total present, absent, and no status
        total_present = sum(1 for student in students if student['Status'] == 'Present')
        total_absent = sum(1 for student in students if student['Status'] == 'Absent')
        total_no_status = sum(1 for student in students if not student['Status'])
        print(total_no_status)

        cursor.close()
        conn.close()

        return render_template(
            'Student_Subjects_Enrollment.html',
            students=students,
            total_present=total_present,
            total_absent=total_absent,
            total_no_status=total_no_status
        )

    @login_required('admin')
    def view_students(self, campus_id):
        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Query to get student details
        query = '''
            SELECT Student_Name AS "Student Name", rfid AS "Username", Password, Year
            FROM Students
            WHERE CampusID = %s 
            ORDER BY Student_Name, Year
        '''
        cursor.execute(query, (campus_id,))
        students = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template('view_students.html', students=students)

                               
    @login_required('admin')
    def student_subjects2(self, rfid):
        # Ensure the RFID is valid
        if not rfid:
            return 'Unauthorized', 403

        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Query for enrolled subjects
        enrolled_query = '''
            SELECT se.Subject_id, s.Subject_Name
            FROM Subjects_Enrolled se
            JOIN Subjects s ON se.Subject_id = s.Subject_id
            WHERE se.RFID = %s
        '''
        cursor.execute(enrolled_query, (rfid,))
        enrolled_subjects = cursor.fetchall()

        # Query for all subjects in the campus for enrollment options
        all_subjects_query = '''
            SELECT s.Subject_id, s.Subject_Name
            FROM Subjects s
            WHERE s.campusid = (SELECT campusid FROM Students WHERE RFID = %s)
              AND s.Subject_id NOT IN (SELECT Subject_id FROM Subjects_Enrolled WHERE RFID = %s)
        '''
        cursor.execute(all_subjects_query, (rfid, rfid))
        available_subjects = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template(
            'student_subjects2.html',
            rfid=rfid,
            enrolled_subjects=enrolled_subjects,
            available_subjects=available_subjects
        )

    @login_required('admin')
    def enroll_subject(self, rfid, subject_id):
        conn = self.get_db_connection()
        cursor = conn.cursor()

        # Enroll the student in the selected subject
        enroll_query = 'INSERT INTO Subjects_Enrolled (RFID, Subject_id) VALUES (%s, %s)'
        cursor.execute(enroll_query, (rfid, subject_id))
        conn.commit()

        cursor.close()
        conn.close()

        flash("Student enrolled in subject successfully.")
        return redirect(url_for('student_subjects2', rfid=rfid))

    @login_required('admin')
    def unenroll_subject(self, rfid, subject_id):
        conn = self.get_db_connection()
        cursor = conn.cursor()

        # Unenroll the student from the selected subject
        unenroll_query = 'DELETE FROM Subjects_Enrolled WHERE RFID = %s AND Subject_id = %s'
        cursor.execute(unenroll_query, (rfid, subject_id))
        conn.commit()

        cursor.close()
        conn.close()

        flash("Student unenrolled from subject successfully.")
        return redirect(url_for('student_subjects2', rfid=rfid))


    @login_required('admin')
    def upload_exam(self, campus_id):
        if request.method == 'POST':
            subject_id = request.form.get('subject_id')
            start_datetime = request.form.get('start_time')  # The datetime string from the form
            end_datetime = request.form.get('end_time')  # The datetime string from the form
            exam_pdf = request.files.get('exam_pdf')

            if not subject_id or not start_datetime or not end_datetime or not exam_pdf:
                flash('All fields are required!', 'danger')
                return redirect(request.url)

            # Save the uploaded PDF to a folder inside static/pdfs
            pdf_filename = secure_filename(exam_pdf.filename)
            pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], 'pdfs', pdf_filename)

            # Ensure the directory exists
            os.makedirs(os.path.dirname(pdf_path), exist_ok=True)

            exam_pdf.save(pdf_path)

            # Convert times from Pakistan Standard Time (PST) to GMT
            pst = pytz.timezone('Asia/Karachi')
            gmt = pytz.timezone('GMT')

            # Parse the datetime strings from the form (including date and time)
            start_time_obj = datetime.strptime(start_datetime, '%Y-%m-%dT%H:%M')  # Format: 'YYYY-MM-DDTHH:MM'
            end_time_obj = datetime.strptime(end_datetime, '%Y-%m-%dT%H:%M')

            # Localize the times to Pakistan Standard Time (Asia/Karachi)
            start_time_obj = pst.localize(start_time_obj)
            end_time_obj = pst.localize(end_time_obj)

            # Convert the times to GMT
            start_time_gmt = start_time_obj.astimezone(gmt)
            end_time_gmt = end_time_obj.astimezone(gmt)

            # Insert the exam details into the database
            conn = self.get_db_connection()
            cursor = conn.cursor()
            query = '''
                INSERT INTO Exams (Subject_id, Exam_PDF, Start_Time, End_Time)
                VALUES (%s, %s, %s, %s)
            '''
            cursor.execute(query, (subject_id, f'pdfs/{pdf_filename}', start_time_gmt, end_time_gmt))
            conn.commit()
            cursor.close()
            conn.close()

            flash('Exam uploaded successfully!', 'success')
            return redirect(url_for('upload_exam', campus_id=campus_id))

        # Fetch subjects for the campus
        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)
        query = '''
            SELECT Subject_id, Subject_Name, year
            FROM Subjects
            WHERE campusid = %s
        '''
        cursor.execute(query, (campus_id,))
        subjects = cursor.fetchall()
        cursor.close()
        conn.close()

        return render_template('upload_exam.html', subjects=subjects, campus_id=campus_id)
    @login_required('admin')
    def update_attendance(self, rfid, new_status, current_status):
        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Fetch current student data using RFID
        query = '''
            SELECT DaysAttended, TotalDays, Fine
            FROM Students
            WHERE RFID = %s
        '''
        cursor.execute(query, (rfid,))
        student = cursor.fetchone()

        if not student:
            return "Student not found", 404

        days_attended = student['DaysAttended']
        total_days = student['TotalDays']
        fine = student['Fine']

        # Update logic based on new status and current status
        if current_status == 'Present':
            if new_status == 'Absent':
                days_attended -= 1  # Decrement days attended
                fine += 100
            elif new_status == 'Leave':
                days_attended -= 1  # Decrement days attended
                # No change to fine

        elif current_status == 'Absent':
            if new_status == 'Present':
                days_attended += 1  # Increment days attended
                fine -= 100
            elif new_status == 'Leave':
                fine -= 100  # Reduce fine
                # No change to days attended

        elif not current_status:  # No status case
            if new_status == 'Present':
                days_attended += 1
                total_days += 1  # Increment both days attended and total days
            elif new_status == 'Absent':
                total_days += 1  # Only increment total days if no previous status
                fine += 100
            elif new_status == 'Leave':
                total_days += 1  # Only increment total days
                # No change to fine

        # Update the student record in the database
        update_query = '''
            UPDATE Students
            SET DaysAttended = %s, TotalDays = %s, Fine = %s
            WHERE RFID = %s
        '''
        cursor.execute(update_query, (days_attended, total_days, fine, rfid))

        # Delete the previous attendance record for the day
        delete_query = '''
            DELETE FROM General_Attendance
            WHERE RFID = %s AND Date = CURDATE()
        '''
        cursor.execute(delete_query, (rfid,))

        # Insert the new attendance record
        attendance_query = '''
            INSERT INTO General_Attendance (RFID, Date, Status, time)
            VALUES (%s, CURDATE(), %s, NOW())
        '''
        cursor.execute(attendance_query, (rfid, new_status))

        conn.commit()
        cursor.close()
        conn.close()

    @login_required('admin')
    def update_all_attendance(self):
        print(session.get('campus_id'))
        campus_id =session.get('campus_id')  # Retrieve campus_id from session

        if not campus_id:
            # Log an error and return a meaningful response if campus_id is not in the session
            app.logger.error("Campus ID is missing in the session.")
            return "Campus ID is missing!", 400

        # Retrieve student RFID and new status from the form for all students
        students = request.form.to_dict()  # Get all form data as a dictionary

        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Iterate over each student and update their attendance
        for student_rfid, new_status in students.items():
            # The form fields will be like "status_<student_rfid>", so we need to extract the rfid
            if student_rfid.startswith('status_'):
                rfid = student_rfid.split('_')[1]  # Extract the student RFID
                current_status = request.form.get(f"current_status_{rfid}")  # Get current status from form
                self.update_attendance(rfid, new_status, current_status)  # Call update_attendance method

        conn.commit()  # Commit all changes to the database
        cursor.close()
        conn.close()

        return redirect(url_for('attendance_students', campus_id=campus_id))


    def upload_picture(self):
        if request.method == 'POST':
            rfid = request.form['rfid']
            picture = request.files['picture']

            if picture:
                filename = secure_filename(picture.filename)
                picture_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

                # Save the picture to the specified folder
                picture.save(picture_path)

                # Store the relative path in the database (assuming '/static/images/' is the base URL)
                relative_path = f"/{app.config['UPLOAD_FOLDER']}/{filename}"

                # Update the student's picture_url in the database
                conn = self.get_db_connection()  # Assume this function exists to get a DB connection
                cursor = conn.cursor()

                try:
                    cursor.execute("""
                        UPDATE Students SET picture_url = %s WHERE RFID = %s
                    """, (relative_path, rfid))
                    conn.commit()
                    flash('Picture uploaded and updated successfully!', 'success')
                except Exception as e:
                    conn.rollback()
                    flash('Error updating picture: ' + str(e), 'danger')
                finally:
                    cursor.close()
                    conn.close()

                return redirect(url_for('upload_picture'))  # Redirect to the upload page

        return render_template('upload_picture.html')  





    def exam_submission(self, exam_id):
        # Fetch exam details from the database
        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)  # Fetch as dictionary

        cursor.execute("""
            SELECT e.Exam_PDF, e.Start_Time, e.End_Time
            FROM Exams e
            WHERE e.Exam_ID = %s
        """, (exam_id,))
        exam_data = cursor.fetchone()

        if not exam_data:
            cursor.close()
            conn.close()
            return "Exam not found", 404

        exam_pdf = exam_data['Exam_PDF']
        exam_start_time = exam_data['Start_Time']
        exam_end_time = exam_data['End_Time']

        # Add 5 hours to the exam_end_time
        exam_end_time = exam_end_time + timedelta(hours=5)

        # Handling POST request to submit the solution
        if request.method == 'POST':
            solution = request.files['solution']

            if solution and solution.filename.endswith('.pdf'):
                filename = secure_filename(solution.filename)
                save_path = os.path.join('path/to/save/pdf', filename)

                # Ensure the directory exists
                os.makedirs(os.path.dirname(save_path), exist_ok=True)

                solution.save(save_path)

                # Save the submission to the database
                cursor.execute("""
                    INSERT INTO Exam_Submissions (Exam_ID, RFID, Solution_PDF, Submission_Time)
                    VALUES (%s, %s, %s, NOW())
                """, (exam_id, session['rfid'], filename))  # Save the solution with the exam_id
                conn.commit()

                # Redirect to the same page to refresh after submission
                return redirect(url_for('exam_submission', exam_id=exam_id))

        cursor.close()
        conn.close()

        return render_template('exam_submission.html',
                               exam_pdf=exam_pdf,
                               exam_start_time=exam_start_time,
                               exam_end_time=exam_end_time,
                               exam_id=exam_id)  # Make sure to pass exam_id to the template
    
    
    def submission_success(self):
        return render_template('submission_success.html')
    
    def submit_solution(self,exam_id):
        # Ensure the user is logged in and has a valid session
        if 'rfid' not in session:
            return redirect(url_for('login'))  # Redirect to login if not authenticated

        solution = request.files.get('solution')

        if solution and solution.filename.endswith('.pdf'):
            filename = secure_filename(solution.filename)
            save_path = os.path.join('static', 'images', 'solutions', filename)

            # Ensure the directory exists
            os.makedirs(os.path.dirname(save_path), exist_ok=True)

            solution.save(save_path)

            # Save the submission details to the database
            conn = self.get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO Exam_Submissions (Exam_ID, RFID, Solution_PDF, Submission_Time)
                VALUES (%s, %s, %s, NOW())
            """, (exam_id, session['rfid'], filename))  # Use exam_id from the URL
            conn.commit()
            cursor.close()
            conn.close()

            # After saving, redirect to the same exam page
            return redirect(url_for('submission_success'))

        return "Invalid file format. Please upload a PDF.", 400



    @login_required('admin')
    def result_students(self,campus_id):
        campus_id = campus_id
        if not campus_id:
            return 'Unauthorized', 403

        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Query to get all students from the specific campus
        query = '''
            SELECT s.rfid, s.Student_Name, s.year
            FROM Students s
            WHERE s.campusid = %s
            ORDER BY s.year
        '''
        cursor.execute(query, (campus_id,))
        students = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template(
            'result_students.html',
            students=students
        )

    @login_required('admin')
    def list_and_update_fine(self, campus_id):
        # Ensure campus_id is provided
        if not campus_id:
            return 'Unauthorized', 403

        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Query to get all students from the specific campus and their current fines
        query = '''
            SELECT s.rfid, s.Student_Name, s.Fine
            FROM Students s
            WHERE s.campusid = %s
            ORDER BY s.Student_Name
        '''
        cursor.execute(query, (campus_id,))
        students = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template(
            'update_fine.html',
            students=students,
            campus_id=campus_id
        )

    @login_required('admin')
    def update_student_fines(self, campus_id):
        if request.method == 'POST':
            conn = self.get_db_connection()
            cursor = conn.cursor()

            # Loop through the posted data and update each student's fines
            for key, value in request.form.items():
                if key.startswith('fine_'):
                    student_id = key.split('_')[1]
                    try:
                        fine_adjustment = int(value)  # Ensure fine adjustment is cast to an integer
                    except ValueError:
                        flash(f"Invalid fine adjustment for student {student_id}")
                        continue

                    # Update fines in the database
                    update_query = '''
                        UPDATE Students
                        SET Fine = Fine + %s
                        WHERE rfid = %s AND campusid = %s
                    '''
                    cursor.execute(update_query, (fine_adjustment, student_id, campus_id))

            conn.commit()
            cursor.close()
            conn.close()

            flash('Fines updated successfully!')
            return redirect(url_for('list_and_update_fine', campus_id=campus_id))




    @login_required('admin')
    def list_and_update_fees(self, campus_id):
        # Ensure campus_id is provided
        if not campus_id:
            return 'Unauthorized', 403

        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Query to get all students from the specific campus and their current fees
        query = '''
            SELECT s.rfid, s.Student_Name, s.FeeAmount
            FROM Students s
            WHERE s.campusid = %s
            ORDER BY s.Student_Name
        '''
        cursor.execute(query, (campus_id,))
        students = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template(
            'students_fees.html',
            students=students,
            campus_id=campus_id
        )

    @login_required('admin')
    def update_student_fees(self, campus_id):
        if request.method == 'POST':
            conn = self.get_db_connection()
            cursor = conn.cursor()

            # Loop through the posted data and update each student's fees
            for key, value in request.form.items():
                if key.startswith('fees_'):
                    student_id = key.split('_')[1]
                    try:
                        new_fees = int(value)  # Ensure new fees are cast to an integer
                    except ValueError:
                        flash(f"Invalid fee amount for student {student_id}")
                        continue

                    # Update fees in the database
                    update_query = '''
                        UPDATE Students
                        SET FeeAmount = %s
                        WHERE rfid = %s AND campusid = %s
                    '''
                    cursor.execute(update_query, (new_fees, student_id, campus_id))

            conn.commit()
            cursor.close()
            conn.close()

            flash('Fees updated successfully!')
            return redirect(url_for('list_and_update_fees', campus_id=campus_id))

    @login_required('admin')
    def attendance_students(self,campus_id):
        campus_id = campus_id
        if not campus_id:
            return 'Unauthorized', 403

        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Query to get all students with their attendance status for today
        query = '''
            SELECT s.rfid, s.Student_Name, ga.Status
            FROM Students s
            LEFT JOIN General_Attendance ga ON s.RFID = ga.RFID AND ga.date = CURDATE()
            WHERE s.campusid = %s
        '''
        cursor.execute(query, (campus_id,))
        students = cursor.fetchall()

        # Summary counts for total present, absent, and no status
        total_present = sum(1 for student in students if student['Status'] == 'Present')
        total_absent = sum(1 for student in students if student['Status'] == 'Absent')
        total_no_status = sum(1 for student in students if not student['Status'])
        print(total_no_status)

        cursor.close()
        conn.close()

        return render_template(
            'attendance_students.html',
            students=students,
            total_present=total_present,
            total_absent=total_absent,
            total_no_status=total_no_status
        )

    @login_required('admin')
    def attendance_employees(self, campus_id):

        if not campus_id:
            return 'Unauthorized', 403

        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # SQL query to fetch employee attendance for today or set default values if no record is found
        query = '''
            SELECT 
                e.RFID,
                e.Employee_Name,
                COALESCE(ea.employee_check_in, 'No status') AS employee_check_in,
                COALESCE(ea.employee_check_out, 'No status') AS employee_check_out,
                COALESCE(ea.Late_status, 'No status') AS Late_status,
                CASE 
                    WHEN ea.employee_check_in IS NOT NULL THEN 'Present'
                    WHEN ea.RFID IS NULL THEN 'Absent'
                    ELSE 'No status'
                END AS Attendance_status
            FROM 
                employee e
            LEFT JOIN 
                Employee_Attendance ea ON e.RFID = ea.RFID AND ea.Attendance_date = CURDATE()
            WHERE e.campusid = %s
            ORDER BY 
                e.Employee_Name ASC
        '''
        cursor.execute(query, (campus_id,))
        employees = cursor.fetchall()
        print(employees)

        # Summary counts for total present, absent, and no status
        total_present = sum(1 for emp in employees if emp.get('Attendance_status') == 'Present')
        total_absent = sum(1 for emp in employees if emp.get('Attendance_status') == 'Absent')
        total_no_status = sum(1 for emp in employees if emp.get('Attendance_status') == 'No status')

        cursor.close()
        conn.close()

        return render_template(
            'attendance_employees.html',
            employees=employees,
            total_present=total_present,
            total_absent=total_absent,
            total_no_status=total_no_status
        )


    @login_required('teacher')
    def teacher_dashboard(self):
        # Get teacher ID from session or user context
        teacherid = session.get('username')  # Adjust this according to how you store the teacher ID
        print(teacherid)
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)

        # Fetch subject IDs for the teacher
        cursor.execute("""
            SELECT subject_id 
            FROM Teachers
            WHERE TeacherId = %s
        """, (teacherid,))
        subjects = cursor.fetchall()
        cursor.close()
        conn.close()

        return render_template('teacher_dashboard.html', subjects=subjects)
        
    @login_required('admin')
    def view_attendance_records(self, subject_id):
        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Fetch students enrolled in the subject
        cursor.execute("""
                SELECT s.RFID, s.student_name, se.SubjectAttended, se.TotalDays
                FROM students s
                JOIN subjects_enrolled se ON s.RFID = se.RFID
                WHERE se.subject_id = %s
                Order by s.student_name
            """, (subject_id,))
        students = cursor.fetchall()

        # Fetch attendance records for the subject
        cursor.execute("""
                SELECT sa.RFID, sa.attendance_status, sa.date
                FROM subject_attendance sa
                WHERE sa.subject_id = %s
            """, (subject_id,))
        attendance_records = cursor.fetchall()

        cursor.close()
        conn.close()

        # Process data: Calculate attendance percentage and prepare data for display
        student_attendance = defaultdict(lambda: {'DaysAttended': 0, 'TotalDays': 0, 'AttendanceRecords': []})

        for record in attendance_records:
            student_rfid = record['RFID']
            if record['attendance_status'] == 'present':
                student_attendance[student_rfid]['DaysAttended'] += 1
            student_attendance[student_rfid]['AttendanceRecords'].append({
                'date': record['date'],
                'status': record['attendance_status']
            })
            student_attendance[student_rfid]['TotalDays'] += 1

        # Populate attendance percentage for each student
        for student in students:
            rfid = student['RFID']
            days_attended = student_attendance[rfid]['DaysAttended']
            total_days = student['TotalDays'] if student['TotalDays'] else 1  # Avoid division by zero
            attendance_percentage = (days_attended / total_days) * 100

            # Add attendance percentage to student data
            student_attendance[rfid]['AttendancePercentage'] = round(attendance_percentage, 1)
            student_attendance[rfid]['student_name'] = student['student_name']
            student_attendance[rfid]['TotalDays'] = student['TotalDays']
            student_attendance[rfid]['SubjectAttended'] = student['SubjectAttended']

        # Render the attendance records on the page
        return render_template('view_attendance_records.html', subject_id=subject_id, students=student_attendance)

        
	

    @login_required('teacher')
    def make_assessment(self):
        if request.method == 'POST':
            assessment_type = request.form['assessment_type']
            total_marks = request.form['total_marks']
            grading_criteria = request.form['grading_criteria']
            subject_id = request.form['subject_id']
            teacherid = session['username']  # Assuming username is used as teacherid

            # Get the current date, month, and year
            current_month = datetime.now().month
            current_year = datetime.now().year
            print("Hello")
            print(current_month)

            conn = self.get_db_connection()
            cursor = conn.cursor(dictionary=True)

            # Check if an assessment of the same type already exists for the month
            cursor.execute("""
                SELECT COUNT(*) AS count FROM Assessments 
                WHERE teacherid = %s 
                  AND subject_id = %s 
                  AND assessment_type = %s 
                  AND MONTH(created_at) = %s 
                  AND YEAR(created_at) = %s
            """, (teacherid, subject_id, assessment_type, current_month, current_year))

            result = cursor.fetchone()
            print(f"Query Result: {result['count']} assessments found.")  # Debug print

            if result['count'] > 0:
                flash(f"An assessment of type '{assessment_type}' has already been created this month.", "error")
                return redirect(url_for('make_assessment'))

            # Proceed to create the assessment if no match is found
            cursor.execute("""
                INSERT INTO Assessments (teacherid, subject_id, assessment_type, total_marks, grading_criteria, created_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
            """, (teacherid, subject_id, assessment_type, total_marks, grading_criteria))

            conn.commit()
            cursor.close()
            conn.close()

            flash("Assessment created successfully.", "success")
            return redirect(url_for('teacher_dashboard'))

        # GET request - Show the form with available subjects
        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT subject_id, subject_name FROM Subjects WHERE teacherid = %s", (session['username'],))
        subjects = cursor.fetchall()
        cursor.close()
        conn.close()

        return render_template('make_assessment.html', subjects=subjects)
        
    @login_required('admin')    
    def view_monthly_assessment_details(self, subject_id):
        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Fetch students enrolled in the subject
        cursor.execute("""
            SELECT s.RFID, s.student_name
            FROM Students s
            JOIN Subjects_Enrolled se ON s.RFID = se.RFID
            WHERE se.subject_id = %s
            ORDER BY s.student_name
        """, (subject_id,))
        students = cursor.fetchall()

        # Fetch monthly assessments for the subject
        cursor.execute("""
            SELECT a.assessment_id, a.subject_id, a.created_at
            FROM Assessments a
            WHERE a.subject_id = %s AND a.assessment_type = 'Monthly'
        """, (subject_id,))
        assessments = cursor.fetchall()

        # Fetch quizzes related to the subject
        cursor.execute("""
            SELECT q.quiz_id, q.subject_id, q.quiz_number, q.created_at
            FROM quizzes q
            WHERE q.subject_id = %s
        """, (subject_id,))
        quizzes = cursor.fetchall()

        # Fetch quiz marks
        cursor.execute("""
            SELECT qm.rfid, qm.quiz_id, qm.marks_achieved
            FROM quiz_marks qm
        """)
        quiz_marks = cursor.fetchall()

        # Fetch monthly marks
        cursor.execute("""
            SELECT am.rfid, am.assessment_id, am.Marks_Acheived
            FROM assessments_marks am
        """)
        assessment_marks = cursor.fetchall()

        cursor.close()
        conn.close()

        # Process the data into a format suitable for display
        assessment_data = defaultdict(lambda: defaultdict(dict))

        for assessment in assessments:
            # Get month name and year
            month_year = assessment['created_at']
            month_name = month_year.strftime('%B')  # Get full month name
            year = month_year.year

            for student in students:
                student_rfid = student['RFID']
                assessment_data[(month_name, year)][student_rfid] = {
                    'student_name': student['student_name'],
                    'quizzes': {'Quiz1': 'NA', 'Quiz2': 'NA', 'Quiz3': 'NA'},
                    'monthly_marks': 'NA',
                    'average_quiz_marks': 'NA',
                    'total_marks': 'NA'
                }

                # Initialize quiz marks for the student
                student_quiz_marks = [qm for qm in quiz_marks if qm['rfid'] == student_rfid]

                for quiz in quizzes:
                    # Ensure that the quiz is linked to the same month and year as the assessment
                    if quiz['subject_id'] == subject_id and quiz['created_at'].strftime('%Y-%m') == month_year.strftime(
                            '%Y-%m'):
                        quiz_number = f'Quiz{quiz["quiz_number"]}'
                        quiz_mark = next(
                            (qm['marks_achieved'] for qm in student_quiz_marks if qm['quiz_id'] == quiz['quiz_id']),
                            'NA'
                        )
                        assessment_data[(month_name, year)][student_rfid]['quizzes'][quiz_number] = quiz_mark

                # Get monthly marks
                monthly_marks = next((am['Marks_Acheived'] for am in assessment_marks if
                                      am['rfid'] == student_rfid and am['assessment_id'] == assessment[
                                          'assessment_id']),
                                     'NA')
                assessment_data[(month_name, year)][student_rfid]['monthly_marks'] = monthly_marks

                # Calculate total marks
                avg_quiz_marks = sum(
                    m for m in assessment_data[(month_name, year)][student_rfid]['quizzes'].values() if m != 'NA')
                total_marks = (avg_quiz_marks + (monthly_marks if monthly_marks != 'NA' else 0))
                assessment_data[(month_name, year)][student_rfid]['total_marks'] = total_marks

        return render_template('view_monthly_assessment_details.html', assessments=assessment_data,
                               subject_id=subject_id)        

    @login_required('teacher')
    def make_assessment(self):
        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            # Fetch subjects for the teacher to display in the dropdown
            teacherid = session['username']
            cursor.execute("""
                SELECT subject_id, subject_name
                FROM Subjects
                WHERE teacherid = %s
            """, (teacherid,))
            subjects = cursor.fetchall()

        except mysql.connector.Error as err:
            print(f"Database Error: {err}")
            flash('A database error occurred while fetching subjects.', 'error')
            subjects = []
        finally:
            cursor.close()
            conn.close()

        if request.method == 'POST':
            assessment_type = request.form['assessment_type']
            total_marks = request.form.get('total_marks')

            # Default total_marks based on assessment type if not provided
            if assessment_type == 'Quiz' and not total_marks:
                total_marks = 15
            elif assessment_type == 'Monthly' and not total_marks:
                total_marks = 35

            # Convert total_marks to integer
            try:
                total_marks = int(total_marks)
            except ValueError:
                total_marks = 0  # Default to 0 or handle error as needed

            grading_criteria = {
                "A*": request.form.get('grade_A_star', 90),
                "A": request.form.get('grade_A', 80),
                "B": request.form.get('grade_B', 70),
                "C": request.form.get('grade_C', 60),
                "D": request.form.get('grade_D', 50),
                "E": request.form.get('grade_E', 40),
                "F": request.form.get('grade_F', 30)
            }
            subject_id = request.form['subject_id']
            created_at = request.form['created_at']  # Get the datetime from form
            created_at = datetime.strptime(created_at, '%Y-%m-%dT%H:%M')  # Convert to datetime object

            conn = self.get_db_connection()
            cursor = conn.cursor(dictionary=True)

            try:
                # Check if an assessment of the same type has already been created this month
                cursor.execute("""
                    SELECT COUNT(*) AS count 
                    FROM Assessments 
                    WHERE teacherid=%s and
                       subject_id = %s 
                      AND assessment_type = %s 
                      AND MONTH(created_at) = %s 
                      AND YEAR(created_at) = %s
                """, (teacherid, subject_id, assessment_type, created_at.month, created_at.year))

                result = cursor.fetchone()
                if result['count'] > 10:
                    flash(f"An assessment of type '{assessment_type}' has already been created this month.", "error")
                    return redirect(url_for('teacher_dashboard'))

                # Determine the next sequence number for the given assessment type and subject
                if assessment_type == 'Monthly':
                    # Start sequence for Monthly assessments from 100
                    cursor.execute("""
                        SELECT COALESCE(MAX(sequence), 99) AS max_sequence
                        FROM Assessments
                        WHERE subject_id = %s AND assessment_type = %s
                    """, (subject_id, assessment_type))
                    last_sequence = cursor.fetchone()['max_sequence']
                    sequence = last_sequence + 1

                elif assessment_type == 'Send-Up':
                    # Start sequence for Send-Up assessments from 150
                    cursor.execute("""
                        SELECT COALESCE(MAX(sequence), 149) AS max_sequence
                        FROM Assessments
                        WHERE subject_id = %s AND assessment_type = %s
                    """, (subject_id, assessment_type))
                    last_sequence = cursor.fetchone()['max_sequence']
                    sequence = last_sequence + 1                 
                else:
                    # Standard sequence for other assessment types
                    cursor.execute("""
                        SELECT COALESCE(MAX(sequence), 0) AS max_sequence
                        FROM Assessments
                        WHERE subject_id = %s AND assessment_type = %s
                    """, (subject_id, assessment_type))
                    last_sequence = cursor.fetchone()['max_sequence']
                    sequence = last_sequence + 1
                    
                   

                # Insert assessment
                cursor.execute("""
                    INSERT INTO Assessments (teacherid, subject_id, assessment_type, total_marks, grading_criteria, sequence, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (teacherid, subject_id, assessment_type, total_marks, json.dumps(grading_criteria), sequence,
                      created_at))

                # Commit the transaction to get the newly created assessment ID
                conn.commit()

                if assessment_type == 'Monthly':
                    # Get the ID of the newly created assessment
                    assessment_id = cursor.lastrowid

                    # Insert three quizzes for the newly created monthly assessment
                    for quiz_number in range(1, 4):
                        cursor.execute("""
                            INSERT INTO quizzes (monthly_assessment_id, quiz_number, created_at, subject_id)
                            VALUES (%s, %s, NOW(), %s)
                        """, (assessment_id, quiz_number, subject_id))

                    # Commit the transaction
                    conn.commit()

                # Success message and redirect
                flash('Assessment created successfully!', 'success')
                return redirect(url_for('teacher_dashboard'))

            except mysql.connector.IntegrityError as err:
                print(f"Integrity Error: {err}")
                conn.rollback()
                flash('An integrity error occurred while creating the assessment.', 'error')
            except mysql.connector.Error as err:
                print(f"Database Error: {err}")
                conn.rollback()
                flash('A database error occurred while creating the assessment.', 'error')
            finally:
                cursor.close()
                conn.close()

        # Render the template with the subjects
        return render_template('make_assessment.html', subjects=subjects)


    @login_required('teacher')
    def view_submissions(self, subject_id):
        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Fetch students and their submissions
        cursor.execute("""
            SELECT st.student_name, es.solution_pdf 
            FROM Exam_Submissions es
            JOIN Students st ON es.rfid = st.rfid
            WHERE es.exam_id IN (
                SELECT e.exam_id 
                FROM Exams e 
                WHERE e.subject_id = %s
            )
            ORDER BY st.student_name
        """, (subject_id,))
        submissions = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template('view_submissions.html', submissions=submissions, subject_id=subject_id)


    
    @login_required('teacher')
    def view_quiz_marks(self, quiz_id):
        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Get the quiz details
        cursor.execute(""" 
            SELECT q.quiz_id, s.subject_name, a.assessment_type, q.quiz_number, q.sequence
            FROM quizzes q
            JOIN Assessments a ON q.monthly_assessment_id = a.assessment_id
            JOIN Subjects s ON q.subject_id = s.subject_id
            WHERE q.quiz_id = %s
        """, (quiz_id,))
        quiz = cursor.fetchone()

        if not quiz:
            return "Quiz not found", 404

        # Get the marks for the quiz
        cursor.execute(""" 
            SELECT qm.rfid, st.student_name, qm.marks_achieved
            FROM quiz_marks qm
            JOIN Students st ON qm.rfid = st.rfid
            WHERE qm.quiz_id = %s
            ORDER BY st.student_name 
        """, (quiz_id,))
        marks = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template('view_quiz_marks.html', quiz=quiz, marks=marks)

    @login_required('teacher')
    def update_marks(self):
        quiz_id = request.form['quiz_id']
        rfid = request.form['rfid']
        new_marks = request.form['new_marks']

        conn = self.get_db_connection()
        cursor = conn.cursor()

        try:
            # Update the marks in the database
            cursor.execute(""" 
                UPDATE quiz_marks 
                SET marks_achieved = %s 
                WHERE quiz_id = %s AND rfid = %s
            """, (new_marks, quiz_id, rfid))
            conn.commit()
            flash('Marks updated successfully!', 'success')
        except Exception as e:
            conn.rollback()
            flash('An error occurred while updating marks.', 'error')
        finally:
            cursor.close()
            conn.close()

        return redirect(url_for('view_quiz_marks', quiz_id=quiz_id))
    @login_required('admin')
    def view_assessment_details(self, subject_id):
        # Establishing database connection
        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Fetch assessments for the given subject
        cursor.execute("""
            SELECT a.assessment_id, a.subject_id, a.total_marks, am.Marks_Acheived, a.sequence, s.subject_name, a.created_at
            FROM Assessments a
            JOIN assessments_marks am ON a.assessment_id = am.assessment_id
            JOIN Subjects s ON a.subject_id = s.subject_id
            WHERE a.subject_id = %s
            ORDER BY a.created_at
        """, (subject_id,))
        assessments = cursor.fetchall()

        # Fetch quizzes and quiz marks for the given subject
        cursor.execute("""
            SELECT q.quiz_id, q.monthly_assessment_id, q.quiz_number, qm.marks_achieved, q.created_at
            FROM quizzes q
            JOIN quiz_marks qm ON q.quiz_id = qm.quiz_id
            JOIN Assessments a ON q.monthly_assessment_id = a.assessment_id
            WHERE a.subject_id = %s
            ORDER BY q.monthly_assessment_id, q.quiz_number
        """, (subject_id,))
        quizzes = cursor.fetchall()

        # Fetch student assessment records for the given subject
        cursor.execute("""
            SELECT s.StudentID, s.student_name, am.assessment_id, am.Marks_Acheived, a.created_at
            FROM Students s
            JOIN assessments_marks am ON s.RFID = am.rfid
            JOIN Assessments a ON am.assessment_id = a.assessment_id
            WHERE a.subject_id = %s
            ORDER BY s.StudentID, a.created_at
        """, (subject_id,))
        student_records = cursor.fetchall()

        cursor.close()
        conn.close()

        # Process data
        processed_data = {}
        for record in student_records:
            student_id = record['StudentID']
            if student_id not in processed_data:
                processed_data[student_id] = {
                    'student_name': record['student_name'],
                    'assessments': {}
                }
            assessment_id = record['assessment_id']
            if assessment_id not in processed_data[student_id]['assessments']:
                processed_data[student_id]['assessments'][assessment_id] = {
                    'marks_achieved': record['Marks_Acheived'],
                    'created_at': record['created_at'],
                    'quizzes': {}
                }

        # Process assessments and quizzes
        for assessment in assessments:
            assessment_id = assessment['assessment_id']
            if assessment_id in processed_data:
                for student_id, data in processed_data.items():
                    if assessment_id in data['assessments']:
                        record = data['assessments'][assessment_id]
                        if assessment['sequence'] == 100:  # Monthly assessment
                            record['monthly_marks_achieved'] = assessment['Marks_Acheived']

        for quiz in quizzes:
            quiz_id = quiz['quiz_id']
            for student_id, data in processed_data.items():
                for assessment_id, record in data['assessments'].items():
                    if quiz['monthly_assessment_id'] in data['assessments']:
                        quiz_number = f'Quiz{quiz["quiz_number"]}'
                        record['quizzes'][quiz_number] = quiz['marks_achieved']

        return render_template('view_assessment_details.html',
                               subject_id=subject_id,
                               processed_data=processed_data)
                               
                               
    
    def enroll_into_subjects(self):
        if request.method == 'POST':
            rfids = request.form['rfids'].split(',')
            subject_ids = request.form['subject_ids'].split(',')

            # Trim whitespace from each RFID and subject ID
            rfids = [rfid.strip() for rfid in rfids]
            subject_ids = [subject_id.strip() for subject_id in subject_ids]
            conn = self.get_db_connection()
            cursor = conn.cursor(dictionary=True)

            try:
                for rfid in rfids:
                    for subject_id in subject_ids:
                        # Insert into Subjects Enrolled
                        cursor.execute("""
                            INSERT INTO Subjects_Enrolled (rfid, subject_id)
                            VALUES (%s, %s)
                        """, (rfid, subject_id))

                # Commit the changes
                conn.commit()
                flash('Students enrolled successfully!', 'success')
                return redirect(url_for('enroll_into_subjects'))  # Redirect back to the enrollment page
            except Exception as e:
                conn.rollback()
                flash('Error enrolling students: ' + str(e), 'danger')
            finally:
                cursor.close()
                conn.close()

        return render_template('enroll_into_subjects.html')
        
    
    @login_required('admin')  # or the appropriate role
    def update_absentee(self):
        if request.method == 'POST':
            rfid = request.form['rfid']
            absentee_id = request.form['absentee_id']  # This is now treated as a string

            conn = self.get_db_connection()
            cursor = conn.cursor(dictionary=True)

            try:
                # Update Absentee_ID in the Students table
                cursor.execute("""
                    UPDATE Students
                    SET AbsenteeID = %s
                    WHERE RFID = %s
                """, (absentee_id, rfid))

                # Commit the changes
                conn.commit()
                flash('Absentee ID updated successfully!', 'success')
            except Exception as e:
                conn.rollback()
                flash('Error updating Absentee ID: ' + str(e), 'danger')
            finally:
                cursor.close()
                conn.close()

            return redirect(url_for('update_absentee'))  # Redirect to the update page

        return render_template('update_absentee.html')
        
        
    @login_required('admin')
    def campus_subjects(self,campus_id):
        # Establishing database connection
        conn = self.get_db_connection()
        cursor = conn.cursor()

        # SQL query to fetch subjects for the selected campus
        query = '''
            SELECT 
                s.subject_id, 
                s.subject_name, 
                t.TeacherId, 
                COUNT(se.RFID) AS TotalStudents
            FROM Subjects s
            LEFT JOIN Teachers t ON s.subject_id = t.subject_id AND s.CampusID = t.campusid
            LEFT JOIN Subjects_Enrolled se ON s.subject_id = se.subject_id
            WHERE s.CampusID = %s
            GROUP BY s.subject_id, s.subject_name, t.TeacherId
            Order by s.subject_name
        '''
        cursor.execute(query, (campus_id,))
        subjects = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template('campus_subjects.html', subjects=subjects, campus_id=campus_id)






    @login_required('teacher')
    def unmarked_assessments(self):
        teacherid = session['username']

        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Get campus ID of the teacher
        cursor.execute("""
            SELECT campusid FROM Teachers WHERE teacherid = %s
        """, (teacherid,))
        campusid = cursor.fetchone()['campusid']

        # Retrieve unmarked assessments within the teacher's campus
        cursor.execute("""
            SELECT a.assessment_id, s.subject_name, a.assessment_type, a.sequence
            FROM Assessments a
            JOIN Subjects s ON a.subject_id = s.subject_id
            WHERE a.teacherid = %s 
              AND s.campusid = %s
              AND a.assessment_id NOT IN (
                  SELECT assessment_id FROM assessments_marks
              )
        """, (teacherid, campusid))

        assessments = cursor.fetchall()

        # Calculate the display sequence number
        for assessment in assessments:
            if assessment['assessment_type'] == 'Monthly':
                assessment['sequence_number'] = assessment['sequence'] - 99
            else:
                assessment['sequence_number'] = assessment['sequence']

        cursor.close()
        conn.close()

        return render_template('unmarked_assessment.html', assessments=assessments)

    @login_required('teacher')
    def unmarked_quizzes(self):
        teacherid = session['username']

        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Retrieve unmarked quizzes for the teacher
        cursor.execute("""
            SELECT q.quiz_id, s.subject_name, a.assessment_type, q.quiz_number, a.sequence AS monthly_sequence
            FROM quizzes q
            JOIN Assessments a ON q.monthly_assessment_id = a.assessment_id
            JOIN Subjects s ON q.subject_id = s.subject_id
            WHERE a.teacherid = %s 
              AND q.quiz_id NOT IN (
                  SELECT quiz_id FROM quiz_marks
              )
        """, (teacherid,))

        quizzes = cursor.fetchall()

        # Calculate the display monthly number
        for quiz in quizzes:
            if quiz['monthly_sequence'] is not None:
                if quiz['assessment_type'] == 'Monthly':
                    quiz['monthly_number'] = quiz['monthly_sequence'] - 99
                else:
                    quiz['monthly_number'] = quiz['monthly_sequence']
            else:
                quiz['monthly_number'] = 'Unknown'  # Handle case where sequence is None

        cursor.close()
        conn.close()

        return render_template('unmarked_quizzes.html', quizzes=quizzes)
	
    @login_required('teacher')
    def marked_quizzes(self):
        teacherid = session['username']

        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Retrieve the marked quizzes for the teacher
        cursor.execute("""
            SELECT q.quiz_id, s.subject_name, a.assessment_type, q.quiz_number, a.sequence AS monthly_sequence
            FROM quizzes q
            JOIN Assessments a ON q.monthly_assessment_id = a.assessment_id
            JOIN Subjects s ON q.subject_id = s.subject_id
            WHERE a.teacherid = %s
              AND q.quiz_id IN (
                  SELECT quiz_id FROM quiz_marks
              )
        """, (teacherid,))

        quizzes = cursor.fetchall()

        # Calculate the display monthly number
        for quiz in quizzes:
            if quiz['monthly_sequence'] is not None:
                if quiz['assessment_type'] == 'Monthly':
                    quiz['monthly_number'] = quiz['monthly_sequence'] - 99
                else:
                    quiz['monthly_number'] = quiz['monthly_sequence']
            else:
                quiz['monthly_number'] = 'Unknown'  # Handle case where sequence is None

        cursor.close()
        conn.close()

        return render_template('marked_quizzes.html', quizzes=quizzes)
        
    
    def register_student(self):
        if request.method == 'POST':
            rfid = request.form['rfid']
            student_name = request.form['student_name']
            picture = request.files['picture']
            password = request.form['password']
            student_id = request.form['student_id']
            absentee_id = request.form['absentee_id']
            year = request.form['year']
            campus_id = request.form['campus_id']

            # Initialize picture_path
            picture_path = None

            if picture:
                filename = secure_filename(picture.filename)
                picture_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

                # Save the picture to the specified folder
                picture.save(picture_path)

                # Store the relative path in the database (assuming '/static/images/' is the base URL)
                relative_path = f"/{app.config['UPLOAD_FOLDER']}/{filename}"

            conn = self.get_db_connection()
            cursor = conn.cursor(dictionary=True)

            try:
                # Insert student data into the database
                cursor.execute("""
                    INSERT INTO Students (RFID, student_name, picture_url, Password, StudentID, AbsenteeID, year, campusid)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (rfid, student_name, relative_path, password, student_id, absentee_id, year, campus_id))

                # Commit the changes
                conn.commit()
                flash('Student registered successfully!', 'success')
                return redirect(url_for('register_student'))  # Redirect to the registration page
            except Exception as e:
                conn.rollback()
                flash('Error registering student: ' + str(e), 'danger')
            finally:
                cursor.close()
                conn.close()

        return render_template('register_student.html')

    @login_required('teacher')
    def view_marks(self, assessment_id):
        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Get the assessment details
        cursor.execute(""" 
            SELECT a.assessment_id, s.subject_name, a.assessment_type
            FROM Assessments a
            JOIN Subjects s ON a.subject_id = s.subject_id
            WHERE a.assessment_id = %s
        """, (assessment_id,))
        assessment = cursor.fetchone()

        if not assessment:
            return "Assessment not found", 404

        # Get the marks for the assessment
        cursor.execute(""" 
            SELECT sm.rfid, st.student_name, sm.Marks_Acheived
            FROM assessments_marks sm
            JOIN Students st ON sm.rfid = st.rfid
            WHERE sm.assessment_id = %s
            ORDER BY st.student_name
        """, (assessment_id,))
        marks = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template('view_marks.html', assessment=assessment, marks=marks)
        
        
    @login_required('teacher')
    def update_2marks(self):
        assessment_id = request.form['assessment_id']
        rfid = request.form['rfid']
        new_marks = request.form['new_marks']

        conn = self.get_db_connection()
        cursor = conn.cursor()

        try:
            # Update the marks in the database
            cursor.execute("""
                UPDATE assessments_marks 
                SET Marks_Acheived = %s 
                WHERE assessment_id = %s AND rfid = %s
            """, (new_marks, assessment_id, rfid))
            conn.commit()
            flash('Marks updated successfully!', 'success')

            # Fetch the assessment details to pass to the template
            cursor.execute("""
                SELECT s.subject_name, a.assessment_type
                FROM Assessments a
                JOIN Subjects s ON a.subject_id = s.subject_id
                WHERE a.assessment_id = %s
            """, (assessment_id,))
            assessment = cursor.fetchone()  # Get the assessment details

            # Fetch the updated list of students and their marks
            cursor.execute("""
                SELECT s.student_name, am.Marks_Acheived
                FROM Students s
                LEFT JOIN assessments_marks am ON s.RFID = am.RFID AND am.assessment_id = %s
                WHERE s.RFID IN (
                    SELECT RFID FROM Subjects_Enrolled WHERE subject_id = (
                        SELECT subject_id FROM Assessments WHERE assessment_id = %s
                    )
                )
                ORDER BY s.student_name ASC
            """, (assessment_id, assessment_id))
            students = cursor.fetchall()

        except Exception as e:
            conn.rollback()
            flash('An error occurred while updating marks.', 'error')
            students = []
            assessment = {}

        finally:
            cursor.close()
            conn.close()

        # Pass the assessment and students data to the template
        return redirect(url_for('view_marks', assessment_id=assessment_id))
        
    

    @login_required('teacher')
    def marked_assessments(self):
        teacherid = session['username']

        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Get campus ID of the teacher
        cursor.execute("""
            SELECT campusid FROM Teachers WHERE teacherid = %s
        """, (teacherid,))
        campusid = cursor.fetchone()['campusid']

        # Retrieve marked assessments within the teacher's campus
        cursor.execute("""
            SELECT a.assessment_id, s.subject_name, a.assessment_type, a.sequence
            FROM Assessments a
            JOIN Subjects s ON a.subject_id = s.subject_id
            WHERE a.teacherid = %s 
              AND s.campusid = %s
              AND a.assessment_id IN (
                  SELECT assessment_id FROM assessments_marks
              )
        """, (teacherid, campusid))

        assessments = cursor.fetchall()

        # Calculate the display sequence number
        for assessment in assessments:
            if assessment['assessment_type'] == 'Monthly':
                assessment['sequence_number'] = assessment['sequence'] - 99
            else:
                assessment['sequence_number'] = assessment['sequence']

        cursor.close()
        conn.close()

        return render_template('marked_assessment.html', assessments=assessments)

    @login_required('teacher')
    def enter_marks(self, assessment_id):
        if request.method == 'POST':
            marks = request.form.getlist('marks')
            rfid_list = request.form.getlist('rfid')
            total_marks = request.form.get('total_marks')  # Get the total_marks from the form

            conn = self.get_db_connection()
            cursor = conn.cursor()

            for rfid, mark in zip(rfid_list, marks):
                mark = float(mark) if mark else 0  # Ensure the mark is a float
                cursor.execute("""
                        INSERT INTO assessments_marks (rfid, assessment_id, total_marks, Marks_Acheived)
                        VALUES (%s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE 
                        total_marks = VALUES(total_marks),
                        Marks_Acheived = VALUES(Marks_Acheived)
                    """, (rfid, assessment_id, total_marks, mark))

            conn.commit()
            cursor.close()
            conn.close()

            return redirect(url_for('unmarked_assessments'))

        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Get campus ID of the teacher
        teacherid = session['username']
        cursor.execute("""
                SELECT campusid FROM Teachers WHERE teacherid = %s
            """, (teacherid,))
        campusid = cursor.fetchone()['campusid']

        # Retrieve students enrolled in the subject and within the teacher's campus
        cursor.execute("""
        		SELECT s.RFID, s.student_name
				FROM Students s
				JOIN Subjects_Enrolled se ON s.RFID = se.RFID
				JOIN Subjects sub ON se.subject_id = sub.subject_id
				WHERE se.subject_id = (
    				SELECT subject_id FROM Assessments WHERE assessment_id = %s
				) AND s.campusid = %s AND sub.campusid = %s
				ORDER BY s.student_name ASC
            """, (assessment_id, campusid, campusid))
  
        students = cursor.fetchall()
        cursor.close()
        conn.close()

        return render_template('enter_marks.html', students=students, assessment_id=assessment_id)

    @login_required('teacher')
    def enter_quiz_marks(self, quiz_id):
        if request.method == 'POST':
            # Get form data
            marks = request.form.getlist('marks')
            rfid_list = request.form.getlist('rfid')
            total_marks = request.form.get('total_marks')  # Get the total_marks from the form

            conn = self.get_db_connection()
            cursor = conn.cursor()

            for rfid, mark in zip(rfid_list, marks):
                mark = float(mark) if mark else 0  # Ensure the mark is a float
                cursor.execute("""
                    INSERT INTO quiz_marks (rfid, quiz_id, marks_achieved)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE 
                    marks_achieved = VALUES(marks_achieved)
                """, (rfid, quiz_id, mark))

            conn.commit()
            cursor.close()
            conn.close()

            return redirect(url_for('unmarked_quizzes'))

        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Get campus ID of the teacher
        teacherid = session['username']
        cursor.execute("""
            SELECT campusid FROM Teachers WHERE teacherid = %s
        """, (teacherid,))
        campusid = cursor.fetchone()['campusid']

        # Retrieve students enrolled in the subject and within the teacher's campus
        cursor.execute("""
            SELECT s.RFID, s.student_name
            FROM Students s
            JOIN Subjects_Enrolled se ON s.RFID = se.RFID
            JOIN Assessments a ON se.subject_id = a.subject_id
            JOIN Subjects sub ON a.subject_id = sub.subject_id
            WHERE a.assessment_id = (
                SELECT monthly_assessment_id FROM quizzes WHERE quiz_id = %s
            ) AND s.campusid = %s AND sub.campusid = %s
            ORDER BY s.student_name ASC
        """, (quiz_id, campusid, campusid))
        students = cursor.fetchall()
        cursor.close()
        conn.close()

        return render_template('enter_quiz_marks.html', students=students, quiz_id=quiz_id)


    @login_required('student')
    def student_dashboard(self):
        if 'rfid' not in session:
            return redirect(url_for('login'))

        rfid = session['rfid']

        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)

        # Fetch student data
        cursor.execute("""
            SELECT student_name, picture_url, DaysAttended, TotalDays 
            FROM Students 
            WHERE RFID = %s
        """, (rfid,))
        student_data = cursor.fetchone()

        if not student_data:
            cursor.close()
            conn.close()
            return redirect(url_for('login'))

        student_name = student_data['student_name']
        image_url = student_data['picture_url']
        days_attended = student_data['DaysAttended']
        TotalDays = student_data['TotalDays']

        # Fetch subject attendance and exam availability
        cursor.execute("""
            SELECT 
                s.subject_name, 
                (se.SubjectAttended / se.TotalDays) * 100 AS attendance_percentage, 
                se.subject_id,
                e.exam_id,
                e.Exam_PDF,
                e.Start_Time,
                e.End_Time
            FROM Subjects_Enrolled se
            JOIN Subjects s ON se.subject_id = s.subject_id
            LEFT JOIN Exams e ON se.subject_id = e.Subject_id
            WHERE se.RFID = %s
        """, (rfid,))
        subject_attendance_data = cursor.fetchall()

        # Process data for rendering
        from datetime import datetime

        now = datetime.now()
        subject_attendance = []
        processed_subjects = set()

        for row in subject_attendance_data:
            subject_id = row['subject_id']
            if subject_id not in processed_subjects:
                # Add the subject row for non-available exams
                subject_attendance.append({
                    'subject_name': row['subject_name'],
                    'attendance_percentage': row['attendance_percentage'],
                    'exam_id': None,
                    'exam_pdf': None,
                    'subject_id': subject_id
                })
                processed_subjects.add(subject_id)

            # Check for available exams
            if row['End_Time'] and row['End_Time'] > now:
                subject_attendance.append({
                    'subject_name': row['subject_name'],
                    'attendance_percentage': row['attendance_percentage'],
                    'exam_id': row['exam_id'],
                    'exam_pdf': row['Exam_PDF'],
                    'subject_id': subject_id
                })

        # Calculate general attendance percentage
        general_attendance_percentage = (days_attended / TotalDays) * 100 if TotalDays > 0 else 0

        # Fetch assessment types and their scores
        cursor.execute("""
            SELECT DISTINCT a.assessment_type
            FROM Assessments a
            JOIN assessments_marks am ON a.assessment_id = am.assessment_id
            WHERE am.rfid = %s
        """, (rfid,))
        assessment_types = cursor.fetchall()

        # Ensure all possible assessment types are displayed
        all_assessment_types = ['Monthly', 'Class', 'Mid', 'Final', 'Send Up', 'Mocks', 'Finals', 'Others','Test Session']
        assessment_types_dict = {type_['assessment_type'] for type_ in assessment_types}

        assessment_types_to_display = [
            type_ for type_ in all_assessment_types if type_ in assessment_types_dict
        ]

        cursor.close()
        conn.close()

        return render_template(
            'student_dashboard.html',
            student_name=student_name,
            image_url=image_url,
            subject_attendance=subject_attendance,
            general_attendance_percentage=general_attendance_percentage,
            assessment_types=assessment_types_to_display
        )

    @login_required('student')
    def assessment_details(self, assessment_type):
        if assessment_type not in ['Monthly', 'Class', 'Mid', 'Final', 'Send Up', 'Mocks', 'Finals', 'Others','Test Session']:
            return redirect(url_for('student_dashboard'))

        # Retrieve RFID from session
        rfid = session.get('rfid')

        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if assessment_type == 'Monthly':
            # Fetch monthly assessments and their details
            cursor.execute("""
                    SELECT a.assessment_id, a.subject_id, a.total_marks, am.Marks_Acheived AS monthly_marks_achieved, a.sequence, s.subject_name, a.created_at
                    FROM Assessments a
                    JOIN assessments_marks am ON a.assessment_id = am.assessment_id
                    JOIN Subjects s ON a.subject_id = s.subject_id
                    WHERE a.assessment_type = %s AND am.rfid = %s
                    ORDER BY a.subject_id, a.created_at
                """, (assessment_type, rfid))
            assessments = cursor.fetchall()

            # Fetch quizzes and quiz marks
            cursor2 = conn.cursor(dictionary=True)
            cursor2.execute("""
                    SELECT q.quiz_id, q.monthly_assessment_id, q.quiz_number, qm.marks_achieved, q.created_at, a.subject_id
                    FROM quizzes q
                    JOIN quiz_marks qm ON q.quiz_id = qm.quiz_id
                    JOIN Assessments a ON q.monthly_assessment_id = a.assessment_id
                    WHERE a.assessment_type = %s AND qm.rfid = %s
                    ORDER BY q.monthly_assessment_id, q.quiz_number
                """, (assessment_type, rfid))
            quizzes = cursor2.fetchall()
            cursor2.close()
        else:
            cursor.execute("""
                    SELECT a.assessment_id, a.subject_id, a.total_marks, am.Marks_Acheived, a.sequence, s.subject_name, a.created_at
                    FROM Assessments a
                    JOIN assessments_marks am ON a.assessment_id = am.assessment_id
                    JOIN Subjects s ON a.subject_id = s.subject_id
                    WHERE a.assessment_type = %s AND am.rfid = %s
                    ORDER BY a.subject_id
                """, (assessment_type, rfid))
            assessments = cursor.fetchall()
            quizzes = []

        cursor.close()
        conn.close()
        

        # Process data
        processed_assessments = {}
        for assessment in assessments:
            subject_id = assessment['subject_id']
            assessment_date = assessment['created_at']
            year_month = assessment_date.strftime('%Y-%m')  # Format for month and year

            if assessment_type == 'Monthly':
                if year_month not in processed_assessments:
                    processed_assessments[year_month] = {
                        'MonthYear': assessment_date.strftime('%B %Y'),
                        'Records': []
                    }
                if subject_id not in [record['subject_id'] for record in processed_assessments[year_month]['Records']]:
                    processed_assessments[year_month]['Records'].append({
                        'subject_name': assessment['subject_name'],
                        'MonthlyMarks_Achieved': 'NA',
                        'QuizMarks': {
                            'Quiz1': 0,
                            'Quiz2': 0,
                            'Quiz3': 0
                        },
                        'TotalMarks': 35,
                        'QuizTotalMarks': 15,
                        'TotalMarks_Achieved': 0,
                        'Grade': 'NA',
                        'subject_id': subject_id
                    })

                # Handle monthly assessment marks
                if assessment['sequence'] >= 100:  # Monthly assessment
                    for record in processed_assessments[year_month]['Records']:
                        if record['subject_id'] == subject_id:
                            record['MonthlyMarks_Achieved'] = assessment['monthly_marks_achieved']

        # Link quizzes to assessments
        if assessment_type == 'Monthly':
            for quiz in quizzes:
                for month_year, data in processed_assessments.items():
                    # Find the right subject and created_at match for quiz assignment
                    for record in data['Records']:
                        if record['subject_id'] == quiz['subject_id'] and quiz['created_at'].strftime(
                                '%Y-%m') == month_year:
                            quiz_number = f'Quiz{quiz["quiz_number"]}'
                            record['QuizMarks'][quiz_number] = quiz['marks_achieved']

            # Calculate total marks and grade
            for month_year, data in processed_assessments.items():
                for record in data['Records']:
                    quiz_marks = [record['QuizMarks'].get(f'Quiz{i}', 0) for i in range(1, 4)]
                    average_quiz_marks = sum(quiz_marks) / len(quiz_marks) if any(quiz_marks) else 0
                    record['TotalMarks_Achieved'] = average_quiz_marks + (
                        record['MonthlyMarks_Achieved'] if record['MonthlyMarks_Achieved'] != 'NA' else 0)
                    record['Grade'] = self.calculate_grade(
                        record['TotalMarks_Achieved'] / record['TotalMarks'] * 100 if record['TotalMarks'] else 0)

        else:
            for subject_id, data in processed_assessments.items():
                percentage = (data['Marks_Acheived'] / data['total_marks']) * 100 if data['total_marks'] else 0
                data['Grade'] = self.calculate_grade(percentage)
            processed_assessments=assessments

        return render_template('assessment_details.html',
                               assessments=processed_assessments,
                               assessment_type=assessment_type)    
                               
    def calculate_grade(self, percentage):
        # Calculate grade based on percentage
        if percentage >= 90:
            return 'A'
        elif percentage >= 80:
            return 'B'
        elif percentage >= 70:
            return 'C'
        elif percentage >= 60:
            return 'D'
        elif percentage >= 50:
            return 'E'
        else:
            return 'F'

    def absentees_list(self):
        if request.method == 'POST':
            action = request.form.get('action')
            date_str = request.form.get('date')
            print(f"Action: {action}, Date from form: {date_str}")  # Debug print

            if date_str:
                try:
                    date_time = datetime.strptime(date_str, '%Y-%m-%d')
                    print(f"Parsed date: {date_time}")  # Debug print
                except ValueError as e:
                    print(f"Date parsing error: {e}")
                    date_time = datetime.now()
            else:
                date_time = datetime.now()
                print("No date provided, using current date")

            if action == 'mark_absent':
                # Call the function to mark absentees for the selected date
                self.rfid_handler.mark_absent_general_attendance(date_time.strftime('%Y-%m-%d %H:%M:%S'))

        else:
            date_time = datetime.now()

        # Fetch the absentees list for the selected or current date
        absentees = self.db.fetch_data("""
            SELECT s.student_name, s.RFID, s.AbsenteeID 
            FROM Students s 
            JOIN General_Attendance ga ON s.RFID = ga.RFID 
            WHERE DATE(ga.date) = %s AND ga.status = 'Absent'
            Order by s.AbsenteeID;
        """, (date_time.date(),))

        absentees = [
            {"student_name": row[0], "RFID": row[1], "AbsenteeID": row[2]}
            for row in absentees
        ]

        print(f"Absentees fetched: {absentees}")  # Debug print

        return render_template('absentees_list.html', absentees=absentees,
                               selected_date=date_time.date().strftime('%Y-%m-%d'))
                               
    def view_all_2students(self, campus_id):
        # Query to fetch all students for the given campus
        query = """
        SELECT student_name, rfid, studentid, year 
        FROM Students 
        WHERE campusid = %s
        ORDER By year, student_name
        """
        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)  # Use dictionary=True for dict-style cursor
        cursor.execute(query, (campus_id,))  # Execute the query with campus_id as parameter
        students = cursor.fetchall()  # Fetch all results from the executed query

        cursor.close()  # Close the cursor
        conn.close()  # Close the connection

        # Render the HTML template for displaying students
        return render_template('view_all_2students.html', students=students)


    def export_to_excel(self):
        if request.method == 'POST':
            # Get the selected date from the form
            date_str = request.form.get('date')  # Get date from the date filter
            if date_str:
                try:
                    # Parse the selected date
                    date_time = datetime.strptime(date_str, '%Y-%m-%d')
                except ValueError as e:
                    # Log or handle the date parsing error
                    print(f"Date parsing error: {e}")
                    date_time = datetime.now()
            else:
                # If no date is provided, use the current date
                date_time = datetime.now()

            # Fetch absentee data for the selected date from your database
            absentees = self.db.fetch_data("""
                    SELECT s.student_name, s.RFID, s.AbsenteeID , ga.date
                    FROM Students s 
                    JOIN General_Attendance ga ON s.RFID = ga.RFID 
                    WHERE DATE(ga.date) = %s AND ga.status = 'Absent';
                """, (date_time.date(),))

            # Convert the data to a pandas DataFrame
            df = pd.DataFrame(absentees, columns=['Student Name', 'RFID', 'Absentee ID','Date'])

            # Save the DataFrame to a BytesIO object as an Excel file
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Absentees')


            output.seek(0)  # Move the cursor to the beginning of the stream

            # Send the file as a response
            return send_file(
                output,
                download_name='absentees_list.xlsx',  # Filename for the download
                as_attachment=True,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )

    def get_db_connection(self):
        return self.db.connect()

    def student_subjects(self, rfid):
      conn = self.get_db_connection()
      cursor = conn.cursor(dictionary=True)

      cursor.execute("""
          SELECT DISTINCT s.subject_name, 
                          MAX(s.subject_id) AS subject_id, 
                          MAX(se.TotalDays) AS TotalDays, 
                          MAX(se.SubjectAttended) AS SubjectAttended
          FROM Subjects s
          JOIN Subjects_Enrolled se ON s.subject_id = se.subject_id
          WHERE se.RFID = %s
          GROUP BY s.subject_name;
      """, (rfid,))

      subjects = cursor.fetchall()

      cursor.execute("SELECT student_name FROM Students WHERE RFID = %s", (rfid,))
      student_name = cursor.fetchone()["student_name"]

      cursor.close()
      conn.close()

      return render_template('student_subjects.html', subjects=subjects, student_name=student_name, rfid=rfid)




    def mark_subject_2attendance(self, subject_id):
        conn = self.get_db_connection()

        if request.method == 'GET':
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT s.* 
                FROM Students s 
                JOIN Subjects_Enrolled se ON s.RFID = se.RFID
                WHERE se.subject_id = %s
                ORDER BY student_name
            """, (subject_id,))

            students = cursor.fetchall()
            cursor.close()

            # Fetch existing attendance records for the current date
            attendance_date = datetime.now().strftime('%Y-%m-%d')
            attendance_records = {}

            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT RFID, attendance_status 
                FROM Subject_Attendance 
                WHERE subject_id = %s AND date = %s
            """, (subject_id, attendance_date))

            for record in cursor.fetchall():
                attendance_records[record['RFID']] = record['attendance_status']

            cursor.close()
            conn.close()

            return render_template('mark_subject_2attendance.html', students=students, subject_id=subject_id,
                                   attendance_records=attendance_records)

        attendance_date = request.form.get('attendance_date', datetime.now().strftime('%Y-%m-%d'))
        attendance_data = request.form.to_dict(flat=False)

        cursor = conn.cursor()

        for rfid in attendance_data.get('rfid', []):
            # Get the attendance status, default to 'present' if not selected
            status = request.form.get(f'attendance_{rfid}', 'present')

            # Check if attendance for this RFID and date already exists
            cursor.execute("""
                SELECT COUNT(*) 
                FROM Subject_Attendance 
                WHERE RFID = %s AND subject_id = %s AND date = %s
            """, (rfid, subject_id, attendance_date))

            record_exists = cursor.fetchone()[0]
            

            if record_exists > 0:
                # Update attendance record if it already exists
                cursor.execute("""
                    UPDATE Subject_Attendance 
                    SET attendance_status = %s, time = %s 
                    WHERE RFID = %s AND subject_id = %s AND date = %s
                """, (status, datetime.now().strftime('%H:%M:%S'), rfid, subject_id, attendance_date))
            else:
                # Insert attendance record if it doesn't already exist
                cursor.execute("""
                    INSERT INTO Subject_Attendance (RFID, subject_id, attendance_status, date, time)
                    VALUES (%s, %s, %s, %s, %s)
                """, (rfid, subject_id, status, attendance_date, datetime.now().strftime('%H:%M:%S')))
                # Update total days attended
                cursor.execute("""
                    UPDATE Subjects_Enrolled 
                    SET TotalDays = TotalDays + 1, SubjectAttended = CASE WHEN %s = 'present' THEN SubjectAttended + 1 ELSE SubjectAttended END 
                    WHERE RFID = %s AND subject_id = %s
                """, (status, rfid, subject_id))

        conn.commit()
        cursor.close()
        conn.close()

        return redirect(url_for('teacher_dashboard'))
       
        
        
        
        
    def subject_records(self, subject_id):
        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT s.student_name, se.SubjectAttended, se.TotalDays, s.RFID 
            FROM Subjects_Enrolled se
            JOIN Students s ON se.RFID = s.RFID
            WHERE se.subject_id = %s
        """, (subject_id,))
        records = cursor.fetchall()
        cursor.close()
        conn.close()
        return render_template('subject_records.html', records=records, subject_id=subject_id)

    def view_attendance(self, rfid, subject_id):
        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT * 
            FROM Subject_Attendance 
            WHERE RFID = %s AND subject_id = %s
        """, (rfid, subject_id))
        attendance_records = cursor.fetchall()
        cursor.close()
        conn.close()
        return render_template('view_attendance.html', attendance_records=attendance_records, rfid=rfid,
                               subject_id=subject_id)

    def view_all_students(self):
        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM Students")
        students = cursor.fetchall()
        cursor.close()
        conn.close()
        return render_template('view_all_students.html', students=students)

    def todays_subjects(self):
        current_day = datetime.now().strftime('%A')  # Get current day name
        conn = self.get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM Subjects WHERE day = %s", (current_day,))
        subjects = cursor.fetchall()
        cursor.close()
        conn.close()
        return render_template('todays_subjects.html', subjects=subjects, current_day=current_day)


    def submit_rfid(self):
        rfid = request.form['rfid']
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if self.rfid_handler.check_employee_exists(rfid):
            date = datetime.now().date()
            existing_check_in = self.db.fetch_data(
                "SELECT * FROM Employee_Attendance WHERE RFID = %s AND Attendance_date = %s", (rfid, date)
            )
            if existing_check_in:
                self.rfid_handler.mark_employee_check_out(rfid, current_time)
            else:
                self.rfid_handler.mark_employee_check_in(rfid, current_time)
        else:
            self.rfid_handler.mark_general_attendance(rfid, current_time)
        return redirect('/')

    def export_bunks(self):
        date = request.args.get('date', '')
        query = """
            SELECT b.RFID, s.student_name, b.subject_id, b.date
            FROM Bunk b
            JOIN Students s ON b.RFID = s.RFID
        """
        if date:
            query += " WHERE b.date = %s"
            params = (date,)
        else:
            params = ()

        try:
            bunk_data = self.db.fetch_data(query, params)
            df = pd.DataFrame(bunk_data, columns=['RFID', 'Student Name', 'Subject ID', 'Date'])
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Bunk Records')
            output.seek(0)
            return send_file(output, download_name='bunk_records.xlsx', as_attachment=True)
        except mysql.connector.Error as e:
            print("MySQL Error:", e)
            return jsonify([])



    def enroll_subjects(self):
        if request.method == 'POST':
            rfid = request.form['rfid']
            selected_subjects = request.form.getlist('subjects')

            if not selected_subjects:
                return render_template('enroll.html', subjects=self.get_all_subjects(),
                                       error="No subjects selected.")

            student_exists = self.db.fetch_data("SELECT * FROM Students WHERE RFID = %s", (rfid,))
            if not student_exists:
                return render_template('enroll.html', subjects=self.get_all_subjects(),
                                       error="RFID does not exist.")

            try:
                for subject_id in selected_subjects:
                    self.db.execute_query(
                        "INSERT INTO Subjects_Enrolled (RFID, subject_id) VALUES (%s, %s)",
                        (rfid, subject_id)
                    )
                return redirect(url_for('students'))
            except mysql.connector.Error as e:
                print("MySQL Error:", e)
                return render_template('enroll.html', subjects=self.get_all_subjects(),
                                       error="An error occurred during enrollment.")

        return render_template('enroll.html', subjects=self.get_all_subjects())

    def get_all_subjects(self):
        return self.db.fetch_data("SELECT subject_id, subject_name FROM Subjects")

    def general_attendance_page(self,rfid):
        try:
            general_attendance_data = db.fetch_data("""
                SELECT ga.RFID, s.student_name, ga.date, ga.time, ga.status
                FROM General_Attendance ga
                JOIN Students s ON ga.RFID = s.RFID
                WHERE ga.RFID = %s
            """, (rfid,))

            return render_template('general_attendance_page.html', general_attendance_data=general_attendance_data,
                                   rfid=rfid)

        except mysql.connector.Error as e:
            print("MySQL Error:", e)
            return render_template('general_attendance_page.html', general_attendance_data=[], rfid=rfid)



    def subject_attendance_page(self,rfid, subject_id):
        try:
            subject_attendance_data = db.fetch_data(
                """
                SELECT sa.RFID, s.student_name, su.subject_name, sa.attendance_status, sa.date, sa.time
                FROM Subject_Attendance sa
                JOIN Students s ON sa.RFID = s.RFID
                JOIN Subjects su ON sa.subject_id = su.subject_id
                WHERE sa.RFID = %s AND sa.subject_id = %s
                """, (rfid, subject_id)
            )
            if not subject_attendance_data:
                subject_attendance_data = []  # Ensure the variable is always a list
            return render_template('subject_attendance_page.html', subject_attendance_data=subject_attendance_data,
                                   rfid=rfid, subject_id=subject_id)
        except mysql.connector.Error as e:
            print("MySQL Error:", e)
            return render_template('subject_attendance_page.html', subject_attendance_data=[], rfid=rfid,
                                   subject_id=subject_id)

    def mark_general_attendance(self):
        return render_template('mark_general_attendance.html')
    def Enroll(self):
        return render_template('enroll.html')

    def register_students(self):
        return render_template('register_student.html')


    def submit_general_attendance(self):
        rfid = request.form['rfid']

        # Define the timezone for Pakistan Standard Time (PST)
        pk_timezone = pytz.timezone('Asia/Karachi')

        # Get the current time and convert it to Pakistan Standard Time
        current_time_utc = datetime.now(pytz.utc)  # Get the current UTC time
        date_time_pk = current_time_utc.astimezone(pk_timezone).strftime('%Y-%m-%d %H:%M:%S')  # Convert to PST

        if int(rfid) == 1234:
            self.rfid_handler.mark_absent_general_attendance(date_time_pk)
        elif int(rfid) == 2345:
            self.rfid_handler.mark_absent_employee_attendance(date_time_pk)
        else:
            if self.rfid_handler.check_employee_exists(rfid):
                date = datetime.now(pk_timezone).date()  # Ensure the date is in PST as well
                existing_check_in = self.rfid_handler.db.fetch_data(
                    "SELECT * FROM Employee_Attendance WHERE RFID = %s AND Attendance_date = %s", (rfid, date)
                )
                if existing_check_in:
                    self.rfid_handler.mark_employee_check_out(rfid, date_time_pk)
                    return redirect(f'/employee_details/{rfid}')
                else:
                    self.rfid_handler.mark_employee_check_in(rfid, date_time_pk)
                    return redirect(f'/employee_details/{rfid}')
            else:
                self.rfid_handler.mark_general_attendance(rfid, date_time_pk)
                return redirect(f'/student_details/{rfid}')

        return redirect(f'/student_details/{rfid}')
    def student_details(self, rfid):
        try:
            # First, try to fetch student data using the provided RFID
            student_data = self.db.fetch_data("SELECT student_name, picture_url,fine FROM Students WHERE RFID = %s", (rfid,))

            if student_data:
                # If found, extract student name and image URL
                student_name = student_data[0][0]
                image_url = student_data[0][1]
                fine=student_data[0][2]
            else:
                # If not found, check in the Alternative_Rfid table
                alternative_result = self.db.fetch_data("SELECT rfid FROM Alternative_Rfid WHERE Card_Rfid = %s",
                                                        (rfid,))

                if alternative_result:
                    # Get the corresponding RFID from Alternative_Rfid
                    alternative_rfid = alternative_result[0][0]

                    # Now fetch student data using the alternative RFID
                    student_data = self.db.fetch_data("SELECT student_name, picture_url,fine FROM Students WHERE RFID = %s",
                                                      (alternative_rfid,))

                    if student_data:
                        student_name = student_data[0][0]
                        image_url = student_data[0][1]
                        fine=student_data[0][2]
                    else:
                        student_name = None
                        image_url = None
                        fine= None
                else:
                    student_name = None
                    image_url = None
                    fine = None

            # Render the template with student details
            return render_template('student_details.html', student_name=student_name, image_url=image_url, rfid=rfid, fine=fine)

        except mysql.connector.Error as e:
            print("MySQL Error:", e)
            return render_template('student_details.html', student_name=None, image_url=None, rfid=rfid)

    def employee_details(self, rfid):
        try:
            # Fetch employee details from the database
            employee_data = self.db.fetch_data(
                "SELECT Employee_Name, Picture_Link, Occupation, employee_check_in "
                "FROM employee "
                "LEFT JOIN Employee_Attendance ON employee.RFID = Employee_Attendance.RFID "
                "WHERE employee.RFID = %s", (rfid,)
            )

            if employee_data:
                employee_name = employee_data[0][0]  # Access the employee name
                image_url = employee_data[0][1]  # Access the image URL
                occupation = employee_data[0][2]  # Access the occupation
                check_in_time = employee_data[0][3]  # Access the check-in time

                return render_template('employee_details.html', employee_name=employee_name,
                                       image_url=image_url, occupation=occupation,
                                       check_in_time=check_in_time, rfid=rfid)
            else:
                return render_template('employee_details.html', employee_name=None,
                                       image_url=None, occupation=None,
                                       check_in_time=None, rfid=rfid)
        except mysql.connector.Error as e:
            print("MySQL Error:", e)
            return render_template('employee_details.html', employee_name=None,
                                   image_url=None, occupation=None,
                                   check_in_time=None, rfid=rfid)

    def mark_subject_attendance(self):
        return render_template('mark_subject_attendance.html')

    def submit_subject_attendance(self):
        rfid = request.form['rfid']
        date_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if int(rfid) == 1234:
            self.rfid_handler.mark_absent_subject_attendance(date_time)
        else:
            self.rfid_handler.mark_subject_attendance(rfid, date_time)
        return redirect(f'/student_details2/{rfid}')



    def student_details2(self, rfid):
        try:
            student_data = self.db.fetch_data("SELECT student_name, picture_url FROM Students WHERE RFID = %s", (rfid,))
            if student_data:
                student_name = student_data[0][0]  # Access the first element of the tuple
                image_url = student_data[0][1]  # Access the second element of the tuple
                return render_template('student_details2.html', student_name=student_name, image_url=image_url,
                                       rfid=rfid)
            else:
                return render_template('student_details2.html', student_name=None, image_url=None, rfid=rfid)
        except mysql.connector.Error as e:
            print("MySQL Error:", e)
            return render_template('student_details2.html', student_name=None, image_url=None, rfid=rfid)




    def attendance(self):
        try:
            attendance_data = self.db.fetch_data("""
                SELECT sa.RFID, s.student_name, su.subject_name, sa.attendance_status
                FROM Subject_Attendance sa
                JOIN Students s ON sa.RFID = s.RFID
                JOIN Subjects su ON sa.subject_id = su.subject_id
            """)
            return render_template('attendance.html', attendance_data=attendance_data)
        except mysql.connector.Error as e:
            print("MySQL Error:", e)
            return jsonify([])

    def students(self):
        try:
            student_data = self.db.fetch_data("SELECT * FROM Students")
            return render_template('students.html', student_data=student_data)
        except mysql.connector.Error as e:
            print("MySQL Error:", e)
            return jsonify([])

    def search_students(self):
        rfid = request.args.get('rfid', '')
        try:
            bunk_data = self.db.fetch_data("""
                SELECT * FROM Students
                WHERE RFID = %s
            """, (rfid,))
            return jsonify(bunk_data)
        except mysql.connector.Error as e:
            print("MySQL Error:", e)
            return jsonify([])

    def employees(self):
        try:
            employee_data = self.db.fetch_data("SELECT * FROM employee")
            return render_template('employee.html', employee_data=employee_data)
        except mysql.connector.Error as e:
            print("MySQL Error:", e)
            return jsonify([])

    def search_employees(self):
        rfid = request.args.get('rfid', '')
        try:
            bunk_data = self.db.fetch_data("""
                SELECT * FROM employee
                WHERE RFID = %s
            """, (rfid,))
            return jsonify(bunk_data)
        except mysql.connector.Error as e:
            print("MySQL Error:", e)
            return jsonify([])


    def subjects(self):
        try:
            subjects_data = self.db.fetch_data("SELECT * FROM Subjects")
            return render_template('subjects.html', subjects_data=subjects_data)
        except mysql.connector.Error as e:
            print("MySQL Error:", e)
            return jsonify([])

    def subject_students(self,subject_id):
        try:
            query = """
            SELECT s.student_name, se.rfid
            FROM subjects_enrolled se
            JOIN students s ON se.rfid = s.rfid
            WHERE se.subject_id = %s
            """
            students = db.fetch_data(query, (subject_id,))
            return render_template('subject_students.html', students=students, subject_id=subject_id)
        except mysql.connector.Error as e:
            print("MySQL Error:", e)
            return jsonify([])

    def general_attendance(self):
        try:
            general_attendance_data = self.db.fetch_data("""
                SELECT ga.RFID, s.student_name, ga.date, ga.time,ga.status
                FROM General_Attendance ga
                JOIN Students s ON ga.RFID = s.RFID
            """)
            current_date = datetime.now().strftime('%Y-%m-%d')
            return render_template('general_attendance.html', general_attendance_data=general_attendance_data,
                                   current_date=current_date)
        except mysql.connector.Error as e:
            print("MySQL Error:", e)
            return jsonify([])

    def search_general_attendance(self):
        rfid = request.args.get('rfid', '')
        start_date = request.args.get('start_date', '')
        end_date = request.args.get('end_date', '')

        try:
            query = """
                SELECT ga.RFID, s.student_name, ga.date, ga.status
                FROM General_Attendance ga
                JOIN Students s ON ga.RFID = s.RFID
            """
            params = []
            if rfid:
                query += " WHERE ga.RFID = %s"
                params.append(rfid)
            if start_date and end_date:
                if rfid:
                    query += " AND ga.date BETWEEN %s AND %s"
                else:
                    query += " WHERE ga.date BETWEEN %s AND %s"
                params.extend([start_date, end_date])
            elif start_date:
                if rfid:
                    query += " AND ga.date >= %s"
                else:
                    query += " WHERE ga.date >= %s"
                params.append(start_date)
            elif end_date:
                if rfid:
                    query += " AND ga.date <= %s"
                else:
                    query += " WHERE ga.date <= %s"
                params.append(end_date)

            general_attendance_data = db.fetch_data(query, params)
            return jsonify(general_attendance_data)
        except mysql.connector.Error as e:
            print("MySQL Error:", e)
            return jsonify([])
    def export_general_attendance(self):
        start_date = request.args.get('start_date', '')
        end_date = request.args.get('end_date', '')

        query = """
            SELECT ga.RFID, s.student_name, ga.date, ga.time,ga.status
            FROM General_Attendance ga
            JOIN Students s ON ga.RFID = s.RFID
        """
        params = []
        if start_date and end_date:
            query += " WHERE ga.date BETWEEN %s AND %s"
            params.extend([start_date, end_date])
        elif start_date:
            query += " WHERE ga.date >= %s"
            params.append(start_date)
        elif end_date:
            query += " WHERE ga.date <= %s"
            params.append(end_date)

        try:
            general_attendance_data = self.db.fetch_data(query, params)

            # Assuming fetch_data returns a list of tuples with (RFID, student_name, date, time)
            df = pd.DataFrame(general_attendance_data, columns=['RFID', 'Student Name', 'Date', 'Time','Status'])

            # Convert timedelta to total seconds and then to HH:MM:SS format
            df['Time'] = df['Time'].apply(lambda x: str(x).split()[2])

            # Now convert 'Time' column to datetime.time objects
            df['Time'] = pd.to_datetime(df['Time'], format='%H:%M:%S').dt.time

            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='General Attendance')
            output.seek(0)
            return send_file(output, download_name='general_attendance.xlsx', as_attachment=True)
        except mysql.connector.Error as e:
            print("MySQL Error:", e)
            return jsonify([])


    def subject_attendance(self):
        try:
            # Get date filter from request args if provided
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')

            query = """
                SELECT sa.RFID, s.student_name, su.subject_name, sa.attendance_status, sa.date, sa.time
                FROM Subject_Attendance sa
                JOIN Students s ON sa.RFID = s.RFID
                JOIN Subjects su ON sa.subject_id = su.subject_id
                WHERE 1=1
            """
            params = []

            if start_date:
                query += " AND sa.date >= %s"
                params.append(start_date)
            if end_date:
                query += " AND sa.date <= %s"
                params.append(end_date)

            subject_attendance_data = self.db.fetch_data(query, tuple(params))
            return render_template('subject_attendance.html', subject_attendance_data=subject_attendance_data)
        except mysql.connector.Error as e:
            print("MySQL Error:", e)
            return jsonify([])

    def search_subject_attendance(self):
        rfid = request.args.get('rfid')
        subject_id = request.args.get('subject_id')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')

        query = """
            SELECT sa.RFID, s.student_name, su.subject_name, sa.attendance_status, sa.date
            FROM Subject_Attendance sa
            JOIN Students s ON sa.RFID = s.RFID
            JOIN Subjects su ON sa.subject_id = su.subject_id
            WHERE 1=1
        """
        params = []

        if rfid:
            query += " AND sa.RFID = %s"
            params.append(rfid)
        if subject_id:
            query += " AND sa.subject_id = %s"
            params.append(subject_id)
        if start_date:
            query += " AND sa.date >= %s"
            params.append(start_date)
        if end_date:
            query += " AND sa.date <= %s"
            params.append(end_date)

        data = self.db.fetch_data(query, tuple(params))
        return jsonify(data)

    def export_subject_attendance_to_excel(self):
        rfid = request.args.get('rfid')
        subject_id = request.args.get('subject_id')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')

        query = """
            SELECT sa.RFID, s.student_name, su.subject_name, sa.attendance_status, sa.date, sa.time
            FROM Subject_Attendance sa
            JOIN Students s ON sa.RFID = s.RFID
            JOIN Subjects su ON sa.subject_id = su.subject_id
            WHERE 1=1
        """
        params = []

        if rfid:
            query += " AND sa.RFID = %s"
            params.append(rfid)

        if subject_id:
            query += " AND sa.subject_id = %s"
            params.append(subject_id)

        if start_date:
            query += " AND sa.date >= %s"
            params.append(start_date)

        if end_date:
            query += " AND sa.date <= %s"
            params.append(end_date)

        data = db.fetch_data(query, tuple(params))

        # Convert the data to a DataFrame
        df = pd.DataFrame(data, columns=['RFID', 'Student Name', 'Subject Name', 'Attendance Status', 'Date', 'Time'])

        # Ensure date and time columns are in the correct format
        df['Date'] = pd.to_datetime(df['Date']).dt.strftime('%Y-%m-%d')

        # Handle the Time column conversion
        df['Time'] = df['Time'].astype(str).str.extract(r'(\d+:\d+:\d+)')[0]

        # Create an Excel file in memory
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Subject Attendance')

            # Get the xlsxwriter workbook and worksheet objects
            workbook = writer.book
            worksheet = writer.sheets['Subject Attendance']

            # Apply date format
            date_format = workbook.add_format({'num_format': 'yyyy-mm-dd'})

            # Set column formats
            worksheet.set_column('E:E', None, date_format)  # Apply date format to Date column

        buffer.seek(0)

        return send_file(buffer, as_attachment=True, download_name='subject_attendance.xlsx',
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    # Your other routes and functions...

    def bunk(self):
        try:
            current_date = datetime.today().strftime('%Y-%m-%d')
            return render_template('bunks.html', current_date=current_date)
        except mysql.connector.Error as e:
            print("MySQL Error:", e)
            return jsonify([])

    def get_bunks(self):
        try:
            self.rfid_handler.find_bunks()  # Call the method to find and record bunked classes
            date_filter = request.args.get('date', datetime.today().strftime('%Y-%m-%d'))
            query = """
                SELECT b.RFID, s.student_name, b.subject_id, b.date
                FROM Bunk b
                JOIN Students s ON b.RFID = s.RFID
            """
            params = ()
            if date_filter:
                query += " WHERE b.date = %s"
                params = (date_filter,)
            bunk_data = self.db.fetch_data(query, params)
            return jsonify(bunk_data)
        except mysql.connector.Error as e:
            print("MySQL Error:", e)
            return jsonify([])

    def search_bunks(self):
        rfid = request.args.get('rfid', '')
        date_filter = request.args.get('date', datetime.today().strftime('%Y-%m-%d'))
        try:
            query = """
                SELECT b.RFID, s.student_name, b.subject_id, b.date
                FROM Bunk b
                JOIN Students s ON b.RFID = s.RFID
                WHERE b.RFID = %s
            """
            params = (rfid,)
            if date_filter:
                query += " AND b.date = %s"
                params += (date_filter,)
            bunk_data = self.db.fetch_data(query, params)
            return jsonify(bunk_data)
        except mysql.connector.Error as e:
            print("MySQL Error:", e)
            return jsonify([])



    def submit_subject_rfid(self):
        rfid = request.form['rfid']
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.rfid_handler.mark_subject_attendance(rfid, current_time)
        return redirect('/')

    @login_required('admin')
    def index(self):
        conn = self.get_db_connection()
        cursor = conn.cursor()

        # SQL query to fetch campuses, total students, and total employees per campus
        query = '''
            SELECT 
                c.CampusID, 
                c.CampusName, 
                COUNT(DISTINCT s.rfid) AS TotalStudents,
                COUNT(DISTINCT e.RFID) AS TotalEmployees
            FROM 
                Campus c
            LEFT JOIN 
                Students s ON c.CampusID = s.campusid
            LEFT JOIN 
                employee e ON c.CampusID = e.campusid
            GROUP BY 
                c.CampusID, c.CampusName
        '''
        cursor.execute(query)
        campuses = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template('index.html', campuses=campuses)




app = Flask(__name__)
db = Database(DB_CONFIG)
routes = AppRoutes(app, db)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
