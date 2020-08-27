from flask import render_template, flash, redirect, url_for, request, abort, current_app, session, Response
from flask_login import current_user, login_required

from . import bp, models, forms
from .forms import TurmaCreationForm, AssignmentCreationForm, LessonForm, AssignmentGradeForm
from .models import AssignmentTaskFile, AssignmentGrade

from app.files import models
from app.models import Assignment, Upload, Comment, Turma, User, Enrollment, PeerReviewForm, CommentFileUpload, Lesson, LessonAttendance
from app.classes.models import AttendanceCode
from wtforms import SubmitField
import app.models

from app import db
from sqlalchemy import or_
import json, zipfile, zipstream, os, datetime, uuid
from pathlib import Path

import app.assignments.formbuilder

from flask_weasyprint import HTML, render_pdf

# View created assignments status
@bp.route("/view/", methods=['GET', 'POST'])
@login_required
def view_assignments():
	if current_user.is_authenticated and app.models.is_admin(current_user.username):
		# Get admin view with all assignments
		clean_assignments_array = app.assignments.models.get_assignment_info()
		classes = app.assignments.models.get_all_class_info()
		turma_choices = [(turma.id, turma.turma_label) for turma in Turma.query.all()]
		return render_template('view_assignments.html',
			assignments_array = clean_assignments_array,
			admin = True,
			classes=classes,
			turma_choices = turma_choices)
	elif current_user.is_authenticated:
		# Get user class
		if Enrollment.query.filter(Enrollment.user_id==current_user.id).first() is not None:
			# Get assignments for this user
			clean_assignments_array = app.assignments.models.get_user_assignment_info (current_user.id)
			return render_template('view_assignments.html', assignmentsArray = clean_assignments_array)
		else:
			flash('You are not part of any class and can not see any assignments. Ask your tutor for help to join a class.', 'warning')
			return render_template('view_assignments.html') # User isn't part of any class - display no assignments
	abort (403)


# View details of a single assignment 
@bp.route("/view/<assignment_id>")
@login_required
def view_assignment_details(assignment_id):
	if current_user.is_authenticated and app.models.is_admin(current_user.username):
		assignment_student_info = app.assignments.models.get_assignment_student_info(assignment_id)
		assignment_info = app.assignments.models.get_assignment_info(assignment_id)
		return render_template('view_assignment_details.html',
			assignment_student_info = assignment_student_info,
			assignment_id = assignment_id,
			assignment_info = assignment_info
			)
	abort (403)


# Route to download an assignment information file
@bp.route('/download/taskfile/<assignment_id>')
@login_required
def download_assignment_file(assignment_id):
	# Check if the user is part of this file's class
	if app.models.is_admin(current_user.username) or db.session.query(
		Enrollment, Assignment).join(
		Assignment, Enrollment.turma_id == Assignment.target_turma_id).filter(
		Enrollment.user_id == current_user.id).filter(
		Assignment.id == assignment_id).first() is not None:
			return app.assignments.models.download_assignment_task_file (assignment_id)
	abort (403)

# Download all uploads of an assignments
@bp.route("/download/<assignment_id>", methods=['GET'])
@login_required
def download_assignment_uploads(assignment_id):
	if current_user.is_authenticated and app.models.is_admin(current_user.username):	
		z = zipstream.ZipFile(mode='w', compression=zipstream.ZIP_DEFLATED)
		
		# Get list of uploads for this assignment filtered by class
		uploads_and_users = db.session.query(Upload, User).join(
			User, Upload.user_id==User.id).filter(
				Upload.assignment_id==assignment_id).all()
		
		if len(uploads_and_users) < 1:
			flash ('No files have been uploaded for this assignment yet.', 'warning')
			return redirect(url_for('assignments.view_assignment_details', assignment_id=assignment_id))
		else:
			upload_folder = Path(current_app.config['UPLOAD_FOLDER'])
			for upload, user in uploads_and_users:
				filepath = os.path.join(upload_folder, upload.filename)
				filename = user.student_number + ' - ' + user.username + '.' + app.files.models.get_file_extension(upload.original_filename)
				z.write(filepath, arcname = filename)
		
			response = Response(z, mimetype='application/zip')
			# Name the zip file with class and assignment names		
			assignment = Assignment.query.get(assignment_id)
			class_label = Turma.query.get(assignment.target_turma_id).turma_label
			filename = class_label + ' - ' + assignment.title + '.zip'
			response.headers['Content-Disposition'] = 'attachment; filename={}'.format(filename)
			return response		
	abort (403)
	
	

# Admin page to set new assignment
@bp.route("/create", methods=['GET', 'POST'])
@login_required
def create_assignment():
	if current_user.is_authenticated and app.models.is_admin(current_user.username):
		form = app.assignments.forms.AssignmentCreationForm()
		form.peer_review_form_id.choices = [(peer_review_form.id, peer_review_form.title) for peer_review_form in PeerReviewForm.query.all()]
		form.target_turmas.choices = [(turma.id, turma.turma_label) for turma in Turma.query.all()]
		if form.validate_on_submit():
			app.assignments.models.new_assignment_from_form(form)
			flash('Assignment successfully created!', 'success')
			return redirect(url_for('assignments.view_assignments'))
		return render_template('assignment_form.html', title='Create Assignment', form=form)
	abort(403)
	
# Admin page to edit assignments
@bp.route("/edit/<assignment_id>", methods=['GET', 'POST'])
@login_required
def edit_assignment(assignment_id):	
	if current_user.is_authenticated and app.models.is_admin(current_user.username):
		assignment = Assignment.query.get(assignment_id)
		form = AssignmentCreationForm(obj=assignment)
		form.peer_review_form_id.choices = [(peer_review_form.id, peer_review_form.title) for peer_review_form in PeerReviewForm.query.all()]
		del form.target_turmas, form.assignment_task_file
		if form.validate_on_submit():
			form.populate_obj(assignment)
			db.session.add(assignment)
			db.session.commit()
			flash('Assignment successfully edited!', 'success')
			return redirect(url_for('assignments.view_assignments'))
		return render_template('assignment_form.html', title='Edit Assignment', form=form)
	abort(403)
	

# Delete all user uploads and comments associated with this assignment
@bp.route("/delete/<assignment_id>", methods=['GET', 'POST'])
@login_required
def delete_assignment(assignment_id):
	if current_user.is_authenticated and app.models.is_admin(current_user.username):
		form = app.user.forms.ConfirmationForm()
		try: 
			assignment = Assignment.query.get(assignment_id)
		except:
			flash ('Could not locate the assignment to be deleted.', 'error')
			return redirect(url_for('assignments.view_assignments'))
		confirmation_message = 'Are you sure you want to delete the following assignment: ' + assignment.title + "?"
		if form.validate_on_submit():
			app.assignments.models.delete_assignment_from_id(assignment_id)
			flash('Assignment ' + str(assignment_id) + ' successfully deleted!', 'success')
			return redirect(url_for('assignments.view_assignments'))
		return render_template('confirmation_form.html',
							   title='Delete assignment',
							   confirmation_message = confirmation_message,
							   form=form)
	abort (403)
	

# Sets the assignment deadline as the previous day, effectively locking the assignment
@bp.route("/close/<assignment_id>", methods=['GET', 'POST'])
@login_required
def close_assignment(assignment_id):
	if current_user.is_authenticated and app.models.is_admin(current_user.username):
		try: 
			assignment = Assignment.query.get(assignment_id)
		except:
			flash ('Could not find the assignment.', 'error')
			return redirect(url_for('assignments.view_assignments'))
		try:
			if app.assignments.models.check_if_assignment_is_over(assignment_id):
				flash ('This assignment is already closed.')
			else:
				assignment.due_date = datetime.datetime.now().date() - datetime.timedelta(days=1)
				db.session.commit()
		except: 
			flash ('An error occured while changing the assignment deadline.', 'error')
		return redirect(url_for('assignments.view_assignment_details', assignment_id = assignment_id))
	abort (403)


############# Peer review routes
# Display an empty review feedback form
@bp.route("/review/<assignment_id>", methods=['GET', 'POST'])
def create_peer_review(assignment_id):
	if request.method == 'POST':
		form_contents = json.dumps(request.form)
		# Submit form
		if app.assignments.models.new_peer_review_from_form (form_contents, assignment_id):
			# The database is now updated with the comment - check the total completed comments
			completed_comments = len(Comment.get_completed_peer_reviews_from_user_for_assignment (current_user.id, assignment_id))
			if completed_comments == 1:
				flash('Peer review 1 submitted succesfully!', 'success')
			elif completed_comments == 2:
				flash('Peer review 2 submitted succesfully!', 'success')
			return redirect(url_for('assignments.view_assignments'))
		else: # The user tried to submit a review without a pending review
			flash('You need to download an assignment before you submit a peer review!', 'warning')
			return redirect(url_for('assignments.view_assignments'))
	else:
		peer_review_form_id = Assignment.query.get(assignment_id).peer_review_form_id	
		form_data = PeerReviewForm.query.get(peer_review_form_id).serialised_form_data
		form_loader = app.assignments.formbuilder.formLoader(form_data, (url_for('assignments.create_peer_review', assignment_id=assignment_id)))
		render_form = form_loader.render_form()
		return render_template('form_builder_render.html', title='Submit peer review', render_form=render_form)
		

# Display an empty review feedback form
@bp.route("/review/create/<upload_id>/teacher", methods=['GET', 'POST'])
@login_required
def create_teacher_review(upload_id):
	if current_user.is_authenticated and app.models.is_admin(current_user.username):
		peer_review_form_id = Assignment.query.join(
			Upload, Upload.assignment_id == Assignment.id).filter(
			Upload.id == upload_id).first().peer_review_form_id
		form_data = PeerReviewForm.query.get(peer_review_form_id).serialised_form_data
		form_loader = app.assignments.formbuilder.formLoader(form_data, (url_for('assignments.create_teacher_review', upload_id=upload_id)))
		render_form = form_loader.render_form()
		
		# Insert the file upload HTML into the rendered form
		#!# Hacky! Is there a better way to merge a file upload field into a preset form?
		# Split at ><div class="form-title"> and before this add our file upload html
		file_upload_html = '''enctype="multipart/form-data">
			<h2>Upload a corrected file</h2>
			<i>This is an optional step.</i>
			<br>
			<br>
			<input type="file" name="file" /> 
			<br>
			<br>
			''' 
		split = render_form.split('>', 1)
		form_html = split[0] + file_upload_html + split[1]
		
		# Get assignment and user details
		assignment_id = Upload.query.get(upload_id).assignment_id
		assignment_info = Assignment.query.get(assignment_id)
		user_info = User.query.get(Upload.query.get(upload_id).user_id)
		class_info = Turma.query.get(assignment_info.target_turma_id)
		
		if request.method == 'POST':
			# Submit the review comment form 
			form_contents = json.dumps(request.form)
			new_comment_id = app.assignments.models.add_teacher_comment_to_upload(form_contents, upload_id)
			flash('Teacher review submitted succesfully!', 'success')
			
			# Deal with a potential uploaded file
			#!# File is being sent anyway, when no file is uploaded
			#!# the result is ImmutableMultiDict([('file', <FileStorage: '' ('application/octet-stream')>)])
			if 'file' in request.files:
				file = request.files['file']
				if file.filename == '':
					pass
				elif file and models.allowed_file_extension(file.filename):
					models.save_comment_file_upload(file, new_comment_id)
					original_filename = models.get_secure_filename(file.filename)
					flash('Your file ' + str(original_filename) + ' was uploaded successfully.', 'success')
			
			# For this assignment (class), get a list of uploads that haven't been commented on by current_user.id
			uploads = Upload.query.join(User, Upload.user_id == User.id).filter(
				Upload.assignment_id == assignment_id).order_by(
				User.student_number.asc()).all()
			for upload in uploads:
				if Comment.query.filter(Comment.file_id == upload.id).filter(Comment.user_id ==current_user.id).first() is None:
					# There is an assignment that hasn't been graded, redirect to the grading page
					return redirect(url_for('assignments.create_teacher_review', upload_id = upload.id))
			# No more assignments to be graded, return to assignment detail page
			flash ('All the assignments have been graded for this class', 'success')
			return redirect(url_for('assignments.view_assignment_details', assignment_id = assignment_id))
		return render_template('files/peer_review_form.html',
			title='Submit a teacher review',
			assignment_info = assignment_info,
			user_info = user_info,
			class_info = class_info,
			form=form_html,
			admin_file_upload = True)
	abort (403)



# Display an empty review feedback form
@bp.route("/grade/<upload_id>", methods=['GET', 'POST'])
@login_required
def grade_assignment(upload_id):
	if current_user.is_authenticated and app.models.is_admin(current_user.username):
		
		# Get assignment and user details
		upload = Upload.query.get(upload_id)
		if upload is None: abort (404)
		assignment_id = upload.assignment_id
		if assignment_id is None: abort (404)
		assignment_info = Assignment.query.get(assignment_id)
		user_info = User.query.get(Upload.query.get(upload_id).user_id)
		class_info = Turma.query.get(assignment_info.target_turma_id)

		grade = AssignmentGrade.query.filter_by(upload_id = upload_id).first()
		if grade is not None:
			form = AssignmentGradeForm (obj = grade)
		else:
			form = AssignmentGradeForm ()
		
		if form.validate_on_submit():
			# Submit the grade
			grade_object = AssignmentGrade(
				upload_id = upload_id,
				grade = form.grade.data,
				user_id = current_user.id)
			db.session.add(grade_object)
			db.session.commit()
			
			# Display a success message
			flash('Work marked as ' + str(grade) + '.', 'success')
			
			# For this assignment (class), get a list of uploads that haven't been graded by current_user.id
			uploads = Upload.query.join(User, Upload.user_id == User.id).filter(
				Upload.assignment_id == assignment_id).order_by(
				User.student_number.asc()).all()
			
			# Check if each upload has been graded
			for upload in uploads:
				if AssignmentGrade.query.filter(AssignmentGrade.upload_id == upload.id).filter(
					AssignmentGrade.user_id == current_user.id).first() is None:
					# There is an assignment that hasn't been graded, redirect to the grading page
					return redirect(url_for('assignments.grade_assignment', upload_id = upload.id))
			# No more assignments to be graded, return to assignment detail page
			flash ('All the assignments have been graded for this class', 'success')
			return redirect(url_for('assignments.view_assignment_details', assignment_id = assignment_id))
		
		return render_template('assignment_grade_form.html',
			title='Grading',
			upload = upload,
			assignment_info = assignment_info,
			user_info = user_info,
			class_info = class_info,
			form = form)
	abort (403)
	
# Accessible route to return a PDF with grades
@bp.route('/view/pdf/<assignment_id>')
@login_required
def view_grades_pdf(assignment_id):
	if current_user.is_authenticated and app.models.is_admin(current_user.username):
		assignment = Assignment.query.get(assignment_id)
		if assignment is None: abort (404)
		
		assignment_student_info = app.assignments.models.get_assignment_student_info(assignment_id)
		assignment_info = app.assignments.models.get_assignment_info(assignment_id)
		
		html = render_template('pdf_grades.html',
			assignment_student_info = assignment_student_info,
			assignment_info = assignment_info,
			assignment_id = assignment_id,
			app_name = current_app.config['APP_NAME'])

		return render_pdf (HTML(string=html))
	abort (403)


# Accessible route to return a PDF with all the grades of a class
@bp.route('/view/class/<turma_id>')
@bp.route('/view/class/<turma_id>/<pdf>')
@login_required
def view_class_grades(turma_id, pdf = False):
	if current_user.is_authenticated and app.models.is_admin(current_user.username):
		turma = Turma.query.get(turma_id)
		if turma is None: abort (404)
		
		# Compile the grades information
		assignments = Assignment.query.filter_by (target_turma_id = turma_id)
		class_grade_info = []
		for enrollment, turma, user in app.classes.models.get_class_enrollment_from_class_id (turma_id):
			user_dict = {}
			user_dict['student_number'] = user.student_number
			user_dict['username'] = user.username

			# Make an assignments array and add grade information to each assignment
			user_assignments = []
			for assignment in assignments:
				assignment_dict = {}
				assignment_dict['id'] = assignment.id
				# For each assignment, get each upload
				upload = Upload.query.filter_by(
					user_id = user.id,
					assignment_id = assignment.id
				).first()

				# If upload was received, add the grade to the array
				if upload is not None:
					grade = AssignmentGrade.query.filter_by(
						upload_id = upload.id
					).first()
					if grade is not None: 
						assignment_dict['grade'] = grade.grade
					else: assignment_dict['grade'] = 'No Grd'
				else:
					assignment_dict['grade'] = 'No Upl'
					
				user_assignments.append (assignment_dict)

			user_dict['user_assignments'] = user_assignments
			class_grade_info.append(user_dict)

		# General assignment info 
		# #!# Can this be removed or refactored?
		assignment_info_array = []
		for assignment in assignments:
			assignment_dict = assignment.__dict__
			assignment_dict['assignment_student_info'] = app.assignments.models.get_assignment_student_info(assignment.id)
			assignment_dict['assignment_info'] = app.assignments.models.get_assignment_info(assignment.id)
			assignment_info_array.append(assignment_dict)
		
		if pdf:
			html = render_template(
				'class_grades_pdf.html',
				class_grade_info = class_grade_info,
				assignments = assignments,
				assignment_info_array = assignment_info_array,
				turma = turma,
				app_name = current_app.config['APP_NAME'])
			return render_pdf (HTML(string=html))
		else:
			return render_template(
				'class_grades.html',
				class_grade_info = class_grade_info,
				assignments = assignments,
				assignment_info_array = assignment_info_array,
				turma = turma,
				app_name = current_app.config['APP_NAME'])
	abort (403)


# Let a receiver or author view a completed peer review
@bp.route("/review/view/<comment_id>")
@login_required
def view_peer_review(comment_id):
	if current_user.id is models.get_file_owner_id (
		Comment.query.get(comment_id).file_id) or current_user.id is app.assignments.models.get_comment_author_id_from_comment(
		comment_id) or app.models.is_admin(current_user.username):
	
		peer_review_form_id = db.session.query(Assignment).join(
			Comment, Assignment.id==Comment.assignment_id).filter(
			Comment.id==comment_id).first().peer_review_form_id
		
		form_contents = json.loads(Comment.query.get(comment_id).comment)
		
		# Get any uploaded file, if applicable
		comment_file_upload = db.session.query(CommentFileUpload).filter_by(
			comment_id = comment_id).first()
		
		
		if current_user.id is app.assignments.models.get_comment_author_id_from_comment(
		comment_id):
			flash('You can not edit this peer review as it has already been submitted.', 'info')
			
		form_data = PeerReviewForm.query.get(peer_review_form_id).serialised_form_data

		form_loader = app.assignments.formbuilder.formLoader(form_data,
															 (url_for('files.view_comments', file_id = Comment.query.get(comment_id).file_id)),
															 submit_label = 'Return',
															 data_array = form_contents)
		render_form = form_loader.render_form()
		return render_template('form_builder_render.html',
							   render_form=render_form, title = 'Peer review',
							   comment_file_upload = comment_file_upload)
		
	else: abort (403)
	
	
# Route to download a library file
@bp.route('/review/download/<comment_file_upload_id>')
@login_required
def download_comment_file_upload(comment_file_upload_id):
	try:
		comment_file_upload = CommentFileUpload.query.get(comment_file_upload_id)
		comment = Comment.query.get(comment_file_upload.comment_id)
		upload = Upload.query.get(comment.file_id)
		upload_owner = User.query.get(upload.user_id)
	except:
		abort (404)
	# Only admin or comment-file-upload's comment's upload's owner can download
	if app.models.is_admin(current_user.username) or upload_owner.id == current_user.id:
		return app.files.models.download_comment_file_upload (comment_file_upload_id)
	abort (403)
	



############# Peer review forms builder routes
from flask_talisman import Talisman, ALLOW_FROM
from app import talisman
# Build temporary expanded content security policy
temp_csp = {
        'default-src': [
            '\'self\'',
            '\'unsafe-inline\'',
            'cdnjs.cloudflare.com',
            'fonts.googleapis.com',
            'fonts.gstatic.com',
            '*.w3.org',
            'kit-free.fontawesome.com'
        ],
        'img-src': '*',
        'style-src': [
            '*',
            '\'self\'',
            '\'unsafe-inline\'',
            '\'unsafe-eval\'',
        ],
        'script-src': [
            '\'self\'',
            '\'unsafe-inline\'',
			'\'unsafe-eval\'',
            'ajax.googleapis.com',
            'code.jquery.com',
            'cdn.jsdelivr.net',
            'cdnjs.cloudflare.com',
        ]
    }
@talisman(content_security_policy=temp_csp)
@bp.route("/form/builder")
def form_builder():
	return render_template('form_builder_index.html')

@bp.route('/form/save', methods=['POST'])
def save():
	if request.method == 'POST':
		form_data = request.form.get('formData')
		if form_data == 'None':
			return 'Error processing request'
		else:
			json_string = r'''{}'''.format(form_data)
			json_data = json.loads(json_string)
			
			peer_review_form = PeerReviewForm()
			peer_review_form.title = json_data['title']
			peer_review_form.description = json_data['description']
			peer_review_form.serialised_form_data = json.dumps(json_data)
			db.session.add(peer_review_form)
			db.session.commit()
		session['form_data'] = form_data
		
	return 'True'

@bp.route('/form/render')
@bp.route('/form/render/<form_id>')
def render(form_id = False):
	if form_id:
		form_data = PeerReviewForm.query.get(form_id).serialised_form_data
	elif not session['form_data']:
		redirect(url_for('main.index'))
	else:
		form_data = session['form_data']
		session['form_data'] = None

	form_loader = app.assignments.formbuilder.formLoader(form_data, (url_for('assignments.submit')))
	render_form = form_loader.render_form()
	
	return render_template('form_builder_render.html', render_form=render_form)

@bp.route('/form/delete/<form_id>')
def delete_peer_review_form(form_id):
	#!# Check if form is in use by any assignments?
	
	PeerReviewForm.query.filter(PeerReviewForm.id == form_id).delete()
	db.session.commit()
	flash ('Form deleted successfully.', 'success')
	return (redirect(url_for('assignments.peer_review_form_admin')))

@bp.route('/form/builder/submit', methods=['POST'])
def submit():
	if request.method == 'POST':
		form = json.dumps(request.form)

		return form

@bp.route("/peer-review/forms/add", methods=['GET', 'POST'])
@login_required
def add_peer_review_form():
	if current_user.is_authenticated and app.models.is_admin(current_user.username):
		return (redirect(url_for('assignments.form_builder')))
	abort(403)

# Admin page to view classes
@bp.route("/peer-review/forms/admin")
@login_required
def peer_review_form_admin():
	if current_user.is_authenticated and app.models.is_admin(current_user.username):
		peer_review_forms = PeerReviewForm.query.all()
		return render_template('manage_peer_review_forms.html', peer_review_forms=peer_review_forms)
	abort (403)

	