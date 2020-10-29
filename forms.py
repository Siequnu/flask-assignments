from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, SelectField, DateField, SelectMultipleField, BooleanField, FormField, TextAreaField, DecimalField
from wtforms.validators import ValidationError, DataRequired
from flask_wtf.file import FileField, FileRequired
from app import db

class AssignmentGradeForm(FlaskForm):
	grade = DecimalField (validators=[DataRequired()])
	submit = SubmitField('Save grade')
	
class AssignmentCreationForm(FlaskForm):
	title = StringField('Assignment title', validators=[DataRequired()])
	description = TextAreaField('Description', validators=[DataRequired()])
	due_date = DateField('Due date', validators=[DataRequired()])
	target_turmas = SelectMultipleField('For class(es)', coerce=int, validators=[DataRequired()])
	peer_review_necessary = BooleanField('Simple peer review', default=False)
	open_peer_review = BooleanField('Open peer review', default=False)
	peer_review_form_id = SelectField('Feedback form', coerce=int, validators=[DataRequired()])
	assignment_task_file = FileField(label='Assignment Task File')
	new_assignment_form_submit = SubmitField('Create')
	
class TurmaCreationForm(FlaskForm):
	turma_number = StringField('Class number', validators=[DataRequired()])
	turma_label = StringField('Class label', validators=[DataRequired()])
	turma_term = StringField('Class term', validators=[DataRequired()])
	turma_year = StringField('Class year', validators=[DataRequired()])
	lesson_start_time = StringField('Class start time', validators=[DataRequired()])
	lesson_end_time = StringField('Class end time', validators=[DataRequired()])
	edit = SubmitField('Edit class')
	submit = SubmitField('Create class')
	
class LessonForm(FlaskForm):
	start_time = StringField('Class start time', validators=[DataRequired()])
	end_time = StringField('Class end time', validators=[DataRequired()])
	date = DateField('Class date', validators=[DataRequired()])
	edit = SubmitField('Edit lesson')
	submit = SubmitField('Create lesson')

		
class ConfirmationForm (FlaskForm):
	submit = SubmitField('Confirm')