from flask import send_from_directory, current_app
from flask_login import current_user

import app.models
from app import db
from app.models import Upload, Download, Assignment, User, Comment, Turma, Enrollment, PeerReviewForm, CommentFileUpload
from app.files import models

from datetime import datetime, date
from dateutil import tz
import arrow, json, time

class AssignmentGrade (db.Model):
	__table_args__ = {'sqlite_autoincrement': True}
	id = db.Column(db.Integer, primary_key=True)
	upload_id = db.Column(db.Integer, db.ForeignKey('upload.id'))
	grade = db.Column(db.Float)
	user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
	
	def __repr__(self):
		return '<Grade {}>'.format(self.id)	

	def delete (self):
		db.session.delete(self)
		db.session.commit()

class AssignmentTaskFile(db.Model):
	__table_args__ = {'sqlite_autoincrement': True}
	id = db.Column(db.Integer, primary_key=True)
	original_filename = db.Column(db.String(140))
	filename = db.Column(db.String(140))
	timestamp = db.Column(db.DateTime, index=True, default=datetime.now())
	user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
	
	def __repr__(self):
		return '<Assignment Task File {}>'.format(self.filename)		


def get_assignment_info (assignment_id = False): 
	assignments_array = []
	if assignment_id:
		assignment_info = db.session.query(Assignment, User, Turma).join(
		User, Assignment.created_by_id == User.id).join(
		Turma, Assignment.target_turma_id==Turma.id).filter(Assignment.id == assignment_id).all()
	else:
		assignment_info = db.session.query(Assignment, User, Turma).join(
		User, Assignment.created_by_id == User.id).join(
		Turma, Assignment.target_turma_id==Turma.id).order_by(Assignment.due_date.asc()).all()
	
	for assignment, user, turma in assignment_info:
		students_in_class = Enrollment.query.filter(Enrollment.turma_id == turma.id).all()
		completed_assignments = Upload.query.filter(Upload.assignment_id == assignment.id).all()
		uncomplete_assignments = len(students_in_class) - len(completed_assignments)
		if assignment.peer_review_necessary == True:
			peer_review_form_title = PeerReviewForm.query.get(assignment.peer_review_form_id).title
		else:
			peer_review_form_title = False
		if assignment.assignment_task_file_id is not None:
			try:
				assignment_task_filename = AssignmentTaskFile.query.get(assignment.assignment_task_file_id).original_filename
			except:
				assignment_task_filename = False
		else:
			assignment_task_filename = False
		assignment_dict = assignment, user, turma, completed_assignments, uncomplete_assignments, assignment_task_filename, peer_review_form_title, students_in_class
		assignments_array.append (assignment_dict)
	return assignments_array

# Returns array of all students in class with added assignment info if applicable
def get_assignment_student_info (assignment_id):
	assignment = Assignment.query.get(assignment_id)
	
	turma_id = assignment.target_turma_id
	
	students = db.session.query(User).join(
		Enrollment, User.id == Enrollment.user_id).filter(
		Enrollment.turma_id == turma_id).order_by(User.student_number.asc()).all()
	
	assignment_detail_info = []
	
	for student in students:
		student_dict = student.__dict__
		try:
			student_dict['upload'] = db.session.query(Upload).filter(
			Upload.user_id == student_dict['id']).filter(
			Upload.assignment_id == assignment_id).first()
		except:
			pass

		if student_dict['upload'] is not None:
			student_dict['grade'] = AssignmentGrade.query.filter_by(upload_id = student_dict['upload'].id).first()
		
		try:
			student_dict['comments'] = db.session.query(Comment).filter(Comment.file_id == student_dict['upload'].id).filter(Comment.pending == 0).all()
		except:
			pass

		# Check if the current user has already commented
		student_dict['already_commented'] = False
		if 'comments' in student_dict:
			for comment in student_dict['comments']:
				if comment.user_id == current_user.id:
					student_dict['already_commented'] = True
		
		assignment_detail_info.append(student_dict)
	return assignment_detail_info
	

def get_user_enrollment_from_id (user_id):
	return db.session.query(Enrollment, User, Turma).join(
		User, Enrollment.user_id==User.id).join(
		Turma, Enrollment.turma_id == Turma.id).filter(
		Enrollment.user_id==user_id).all()

def get_all_class_info():
	return Turma.query.all()

def reset_user_enrollment (user_id):
	if Enrollment.query.filter(Enrollment.user_id==user_id).first() is not None:
		Enrollment.query.filter(Enrollment.user_id==user_id).delete()
		db.session.commit()

def enroll_user_in_class (user_id, turma_id):
	if Enrollment.query.filter(Enrollment.user_id==user_id).filter(Enrollment.turma_id==turma_id).first() is None:
		new_enrollment = Enrollment(user_id = user_id, turma_id = turma_id)
		db.session.add(new_enrollment)
		db.session.commit()

def get_user_assignment_info (user_id, assignment_id = False):
	
	assignments = []
	if assignment_id:
		assignments.append(Assignment.query.get(assignment_id))
	else:
		# Get user enrollment, then fetch and compile assignments for each class
		turma_ids = db.session.query(
			User, Enrollment).join(
			Enrollment, User.id == Enrollment.user_id).filter(
			User.id==user_id).all()
		for user, enrollment in turma_ids:
			assignments_array = get_assignments_from_turma_id (enrollment.turma_id)
			for assignment in assignments_array:
				assignments.append (assignment)
	
	clean_assignments_array = []
	for assignment in assignments:
		# Convert each SQL object into a  __dict__, then add extra keys for the template
		assignment_dict = assignment.__dict__
		
		assignment_dict['assignment_is_past_deadline'] = check_if_assignment_is_over(assignment_dict['id'])
		assignment_dict['humanized_due_date'] = arrow.get(assignment_dict['due_date']).shift(hours=+16).humanize()
		
		if assignment_dict['assignment_task_file_id'] is not None:
			assignment_dict['assignment_task_filename'] = AssignmentTaskFile.query.get(assignment_dict['assignment_task_file_id']).original_filename
		else:
			assignment_dict['assignment_task_filename'] = False
		
		# If user has submitted assignment, get original filename
		if Upload.query.filter_by(assignment_id=assignment_dict['id']).filter_by(user_id=user_id).first() is not None:
			assignment_dict['submitted_filename']= Upload.query.filter_by(
				assignment_id=assignment_dict['id']).filter_by(user_id=user_id).first().original_filename
			#!# Why not just sent the whole upload. Pages looking for submitted_filename can just open the upload object
			assignment_dict['upload'] = Upload.query.filter_by(
				assignment_id=assignment_dict['id']).filter_by(user_id=user_id).first()
			# Check for uploaded or pending peer-reviews
			# This can either be 0 pending and 0 complete, 0/1 pending and 1 complete, or 0 pending and 2 complete
			completed_peer_reviews = Comment.get_completed_peer_reviews_from_user_for_assignment (user_id, assignment_dict['id'])
			assignment_dict['complete_peer_review_count'] = len(completed_peer_reviews)
			assignment_dict['completed_peer_review_objects'] = completed_peer_reviews
			
		clean_assignments_array.append(assignment_dict)
	if assignment_id:
		# Just return the first result
		return clean_assignments_array.pop()
	else: # Return an array of all assignments
		return clean_assignments_array

def get_peer_review_form_from_upload_id (upload_id):
	return db.session.query(
		Assignment).join(
		Upload,Assignment.id==Upload.assignment_id).filter(
		Upload.id == upload_id).first().peer_review_form_id

def get_received_peer_review_count (user_id):
	return db.session.query(Comment).join(
		Upload, Comment.file_id==Upload.id).filter(Upload.user_id==user_id).count()

def get_assignment_upload_progress_bar_percentage (user_id):
	assignments_for_user = len(db.session.query(Assignment, Enrollment).join(
		Enrollment, Assignment.target_turma_id == Enrollment.turma_id).filter(
		Enrollment.user_id == user_id).all())

	completed_assignments = db.session.query(Assignment).join(
		Upload, Assignment.id==Upload.assignment_id).filter(Upload.user_id==current_user.id).count()
	if assignments_for_user > 0:
		return int(float(completed_assignments)/float(assignments_for_user) * 100)
	else:
		return 100
	
def get_peer_review_progress_bar_percentage (user_id):
	peer_review_assignments_for_user = len(db.session.query(Assignment, Enrollment).join(
		Enrollment, Assignment.target_turma_id == Enrollment.turma_id).filter(
		Enrollment.user_id == user_id).filter(Assignment.peer_review_necessary == True).all())
	
	total_peer_reviews_expected = peer_review_assignments_for_user * 2 # At two peer reviews per assignment
	
	total_completed_peer_reviews = Comment.query.filter_by(user_id=user_id).filter_by(pending=False).count()
	if total_peer_reviews_expected > 0:
		return int(float(total_completed_peer_reviews)/float(total_peer_reviews_expected) * 100)
	else:
		return 100

def get_total_completed_peer_reviews (user_id):
	return Comment.query.filter_by(user_id=user_id).filter_by(pending=False).count()
	
def get_comment_author_id_from_comment (comment_id):
	return Comment.query.get(comment_id).user_id

def get_assignments_from_turma_id (turma_id):
	return Assignment.query.filter_by(target_turma_id=turma_id).order_by(Assignment.due_date.asc()).all()

def new_assignment_from_form (form):
	if form.assignment_task_file.data is not None:
		file = form.assignment_task_file.data
		random_filename = app.files.models.save_file(file)
		original_filename = app.files.models.get_secure_filename(file.filename)
		assignment_task_file = AssignmentTaskFile (
			original_filename=original_filename,
			filename = random_filename,
			user_id = current_user.id
		)
		db.session.add(assignment_task_file)
		db.session.flush() # Access the assignment_task_file.id field from db
	
	for turma_id in form.target_turmas.data:
		assignment = Assignment(
			title=form.title.data, 
			description=form.description.data, 
			due_date=form.due_date.data,
			target_turma_id=turma_id, 
			created_by_id=current_user.id,
			peer_review_necessary= form.peer_review_necessary.data,
			open_peer_review= form.open_peer_review.data,
			peer_review_form_id=form.peer_review_form_id.data)
		
		if form.assignment_task_file.data is not None:
			assignment.assignment_task_file_id=assignment_task_file.id
	
		db.session.add(assignment)
		db.session.commit()

def update_assignment_task_file (assignment_id, file):
	assignment = Assignment.query.get(assignment_id)
	
	random_filename = app.files.models.save_file(file)
	original_filename = app.files.models.get_secure_filename(file.filename)

	assignment_task_file = AssignmentTaskFile (
		original_filename=original_filename,
		filename = random_filename,
		user_id = current_user.id
		)
	db.session.add(assignment_task_file)
	db.session.flush() # Access the assignment_task_file.id field from db

	# Point the assignment object to the newly uploaded file
	assignment.assignment_task_file_id=assignment_task_file.id
	db.session.commit ()

def delete_assignment_from_id (assignment_id):	
	
	# Delete all comments and comment uploads for those uploads
	comments = Comment.query.filter_by(assignment_id=assignment_id).all()
	for comment in comments:
		# Delete any comment uploads
		for comment_file_upload in CommentFileUpload.query.filter_by (comment_id = comment.id).all():
			db.session.delete (comment_file_upload)
		
		db.session.delete(comment)
	
	# Delete all upload and grades records for this assignment
	for upload in Upload.query.filter_by (assignment_id=assignment_id).all():
		# Find and delete any grades for these uploads
		for grade in AssignmentGrade.query.filter_by (upload_id = upload.id).all():
			db.session.delete (grade)
		
		db.session.delete(upload)

	# Get a list of any task files
	assignment_task_file_id = Assignment.query.get(assignment_id).assignment_task_file_id
	
	# Delete assignment first, as this references the task files (foreign key)
	Assignment.query.filter_by(id=assignment_id).delete()

	# Delete assignment_task_file, if there are no other assignments that reference it
	task_file_links = Assignment.query.filter_by (assignment_task_file_id = assignment_task_file_id).all()
	if len(task_file_links) < 1: # i.e., we have deleted the last assignment that used this
		AssignmentTaskFile.query.filter_by(id=assignment_task_file_id).delete()

	db.session.commit()
	return True

def add_teacher_comment_to_upload (form_contents, upload_id):
	comment = Comment(
		comment = form_contents, 
		user_id = current_user.id,
		file_id = upload_id, 
		pending = False,
		timestamp = datetime.now(),
		assignment_id = Upload.query.get(upload_id).assignment_id)
	db.session.add(comment)
	db.session.flush() # Access the new comment ID
	new_comment_id = comment.id
	db.session.commit()
	return new_comment_id

def delete_all_comments_from_upload_id (upload_id):
	comments = Comment.query.filter_by(file_id=upload_id).all()
	if comments is not None:
		for comment in comments:
			
			# Delete any comment_file_uploads associated with any comments
			comment_file_uploads = CommentFileUpload.query.filter_by(comment_id=comment.id).all()
			if comment_file_uploads is not None:
				for upload in comment_file_uploads:
					db.session.delete(upload)
					db.session.commit()
			
			# Delete the comment now
			db.session.delete(comment)
	db.session.commit()

def delete_all_comments_from_user_id (user_id):
	comments = Comment.query.filter_by(user_id=user_id).all()
	if comments is not None:
		for comment in comments:
			db.session.delete(comment)
	db.session.commit()

def delete_all_grades_from_user_id (user_id):
	# Find the uploads that this user has made
	uploads = Upload.query.filter_by (user_id = user_id).all()
	for upload in uploads:
		# For each upload, delete any associated grades
		grades = AssignmentGrade.query.filter_by(upload_id=upload.id).all()
		for grade in grades:
			db.session.delete (grade)
	db.session.commit()

def new_peer_review_from_form (form_contents, assignment_id):
	# Check if user has any previous downloads with pending peer reviews
	pending_assignment = Comment.get_pending_status_from_user_id_and_assignment_id (current_user.id, assignment_id)
	if pending_assignment is not None:
		# User has a pending peer review - update the empty comment field with the contents of this form and remove pending status
		# If there is no pending status - user has not yet downloaded a file, so don't accept the review
		Comment.update_pending_comment_with_contents(pending_assignment.id, form_contents)
		return True
	else:
		return False
		

# Return an object with a summary of all feedback
def get_feedback_summary (upload_id):
	upload = Upload.query.get(upload_id)
	
	# Get the assignment, in order to get the feedback form
	assignment = Assignment.query.get(upload.assignment_id)
	peer_review_form = PeerReviewForm.query.get(assignment.peer_review_form_id)
	form_data = json.loads(peer_review_form.serialised_form_data)

	# Loop through form data and build a question and answer dictionar
	question_and_answer_dict = {}
	for field in form_data['fields']:
		
		# Format the title ('Question two ' is saved as 'question_two_'
		formatted_title = field['title'].lower().replace(' ', '_').replace('(', '').replace(')', '').replace(',', '').replace('&', '').replace('-', '')
		
		# If this is a multiple choice field, get the choices
		choices = []
		if field['type'] == 'element-multiple-choice':
			for choice in field['choices']:
				choices.append ({
					'title': choice['title'],
					'count': 0
				})

		question_and_answer_dict[formatted_title] = {
			'type': field['type'],
			'beautified_title': field['title'],
			'choices': choices,
			'answers': [],
			'analysis': []
		}
	
	# Add the answers to each question
	for comment, user in app.files.models.get_peer_reviews_from_upload_id (upload_id):
		comment_data = json.loads (comment['comment'])
		del comment_data['_csrf_token']
		for question, answer in comment_data.items():
			
			# If we already have this question in the dict, append the new answer
			if question in question_and_answer_dict:
				question_and_answer_dict[question]['answers'].append (answer)

	# Loop through each question_title: {object} in the array
	for question_title, question_object in question_and_answer_dict.items():
		
		# If the type is multiple choice
		if question_object['type'] == 'element-multiple-choice':
			
			# For each answer title
			for answer in question_object['answers']:
				
				# Find the matching title in choices
				for question_choice in question_object['choices']:
					if question_choice['title'] == answer:
						
						# Increment the counter
						question_choice['count'] += 1

			# All the answers have been counted, now analyse the stats
			for question_choice in question_object['choices']:
				total_choices = len(question_object['choices'])
				total_answers = len(question_object['answers'])
				
				try:
					question_choice['percentage_of_total_answers'] = int(question_choice['count'] / total_answers * 100)
				except:
					question_choice['percentage_of_total_answers'] = 0

			# Calculate the average choice by converting each choice to a value (i.e., 1-5)
			choice_array = []
			for question_index, question_choice in enumerate(question_object['choices']):
				choice_index = question_index + 1 # i.e., start at 1, not 0
				iterator = 0
				while iterator < question_choice['count']:
					choice_array.append (choice_index)
					iterator += 1
			
			try:
				question_object['analysis'] = round(sum(choice_array) / len(choice_array), 1)
			# i.e., most likely divide by zero error
			except:
				question_object['analysis'] = 0
		
		elif question_object['type'] == 'element-paragraph-text' or question_object['type'] == 'element-single-line-text':
			concatenated_strings = ''
			for answer in question_object['answers']:
				concatenated_strings += answer + ', '
			question_object['analysis'] = concatenated_strings

	return question_and_answer_dict


def check_if_assignment_is_over (assignment_id):
	due_date = Assignment.query.get(assignment_id).due_date
	due_datetime = datetime(due_date.year, due_date.month, due_date.day)
	date_format = "%Y-%m-%d"
	# Create datetime objects from the strings
	now = datetime.strptime(time.strftime(date_format), date_format)
	
	if due_datetime >= now: # Assignment is still open
		return False
	else: # Assignment closed
		return True

def last_uploaded_assignment_timestamp (user_id):
	if Upload.query.filter_by(user_id=user_id).order_by(Upload.timestamp.desc()).first() is not None:
		last_upload_timestamp = Upload.query.filter_by(user_id=user_id).order_by(Upload.timestamp.desc()).first().timestamp
		return arrow.get(last_upload_timestamp, tz.gettz('Asia/Hong_Kong')).humanize()
	else: return False

def last_incoming_peer_review_timestamp (user_id):
	if db.session.query(Comment).join(Upload,Comment.file_id==Upload.id).filter(
		Upload.user_id==user_id).order_by(Comment.timestamp.desc()).first() is not None:
		latest_incoming_peer_review = db.session.query(Comment).join(Upload,Comment.file_id==Upload.id).filter(
			Upload.user_id==user_id).order_by(Comment.timestamp.desc()).first().timestamp
		return arrow.get(latest_incoming_peer_review, tz.gettz('Asia/Hong_Kong')).humanize() 
	else: return False	

def download_assignment_task_file (assignment_id):
	if db.session.query(Assignment, AssignmentTaskFile).join(
		AssignmentTaskFile, Assignment.assignment_task_file_id ==  AssignmentTaskFile.id).filter(
		Assignment.id == assignment_id).first() is not None:
		
		result = db.session.query(Assignment, AssignmentTaskFile).join(
		AssignmentTaskFile, Assignment.assignment_task_file_id ==  AssignmentTaskFile.id).filter(
		Assignment.id == assignment_id).first()
		
		return send_from_directory(filename=result.AssignmentTaskFile.filename,
								   directory=current_app.config['UPLOAD_FOLDER'],
								   as_attachment = True,
								   attachment_filename = result.AssignmentTaskFile.original_filename)
	else:
		return False

# Method to attach a grade to an assignment. This will overwrite any existing grades
def grade_assignment_upload (upload_id, grade):
	# Is there already an existing grade?
	existing_grade = AssignmentGrade.query.filter_by(upload_id = upload_id).first()
	if existing_grade is not None:
		existing_grade.grade = grade
		db.session.commit ()
	else:
		# Submit the grade
		grade_object = AssignmentGrade(
			upload_id = upload_id,
			grade = grade,
			user_id = current_user.id)
		db.session.add(grade_object)
		db.session.commit()