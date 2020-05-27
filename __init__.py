from flask import Blueprint

bp = Blueprint('assignments', __name__, template_folder = 'templates')

from . import routes, models, forms