import datetime
import os
from os.path import normpath

from fabric.decorators import runs_once, roles, task
from fabric.operations import put, prompt
from fabric.colors import green, red
from fabric.api import local, cd, sudo

# Import project settings 
try:
    from fabconfig import *
except ImportError:
    import sys
    print "You need to define a fabconfig.py file with your project settings"
    sys.exit()

# SETUP

def setup_venv_local():
	local('virtualenv --no-site-packages --distribute -p python2.7 venv')
	local('virtualenv --relocatable venv')
	local('source venv/bin/activate && pip install -r web/deploy/requirements.txt')

def setup_django_local():
	local('source venv/bin/activate && cd web && ./manage.py syncdb')

def setup_submodules():
	local('git submodule update --init')

def setup_local():
	setup_venv_local()
	setup_django_local()
	setup_submodules()

#####

def clean():
	local('rm -rf venv')

def bootstrap():
	bootstrap_copy()
	bootstrap_compile()

def bootstrap_compile():
	local('recess --compile less/bootstrap.less > web/static/css/styles.css')
	local('recess --compile less/responsive.less > web/static/css/styles-responsive.css')
	
	bootstrap_compile_compressed()

def bootstrap_compile_compressed():	
	local('recess --compile --compress less/bootstrap.less > web/static/css/styles.min.css')
	local('recess --compile --compress less/responsive.less > web/static/css/styles-responsive.min.css')

def bootstrap_copy():
	local('cp bootstrap/bootstrap/js/bootstrap.min.js web/static/js')
	local('cp bootstrap/bootstrap/img/glyphicons-halflings* web/static/img')

########

def _get_commit_id():
    """
    Return the commit ID for the branch about to be deployed
    """
    return local('git rev-parse HEAD', capture=True)[:20]

def notify(msg):
    bar = '+' + '-' * (len(msg) + 2) + '+'
    print green('')
    print green(bar)
    print green("| %s |" % msg)
    print green(bar)
    print green('')

# Deployment tasks

def deploy():
	notify('Deploying to %s' % env.hosts)
	current = _get_commit_id()[0:7]
	env.version = prompt(red('Choose tag/commit to build from (%s): ' % current))
	if env.version is '':
		env.version = current
	
	# set_ssh_user()
	pack()
	deploy_code(env.build_file)

	update_virtualenv()
	switch_symlink()
	custom()
	# migrate()
	deploy_nginx_config()
	
	reload_python_code()
	reload_nginx()
	delete_old_builds()
	

def set_ssh_user():
    if 'TANGENT_USER' in os.environ:
        env.user = os.environ['TANGENT_USER']
    else:
        env.user = prompt(red('Username for remote host? [default is current user] '))
    if not env.user:
        env.user = os.environ['USER']


def pack():
	notify("Building from refspec %s" % env.version)
	env.build_file = '/tmp/build-%s.tar.gz' % str(env.version)
	local('git archive --format tar %s %s | gzip > %s' % (env.version, env.web_dir, env.build_file))
	
	now = datetime.datetime.now()
	env.build_dir = '%s-%s' % (env.build, now.strftime('%Y-%m-%d-%H-%M'))
	env.code_dir = '%s/%s' % (env.builds_dir, env.build_dir)

def upload(local_path, remote_path=None):
    """
    Uploads a file
    """
    if not remote_path:
        remote_path = local_path
    notify("Uploading %s to %s" % (local_path, remote_path))
    put(local_path, remote_path)

def unpack(archive_path):
	notify('Unpacking files')
	sudo('mkdir -p %(builds_dir)s' % env)
	with cd(env.builds_dir):
		sudo('tar xzf %s' % archive_path)
		
		# Create new build folder
		sudo('if [ -d "%(build_dir)s" ]; then rm -rf "%(build_dir)s"; fi'% env)
		sudo('mv %(web_dir)s %(build_dir)s' % env)

		# Add file indicating Git commit
		sudo('echo -e "refspec: %s\nuser: %s" > %s/build-info' % (env.version, env.user, env.build_dir))

		# Remove archive
		sudo('rm %s' % archive_path)

def deploy_code(archive_file):
	upload(archive_file)
	unpack(archive_file)

def update_virtualenv():
	"""
	Install the dependencies in the requirements file
	"""
	notify('Updating venv')
	with cd(env.code_dir):
		sudo('source %s/bin/activate && pip install -r deploy/requirements.txt' % env.virtualenv)

def migrate():
    """
    Apply any schema alterations
    """
    notify("Applying database migrations")
    with cd(env.code_dir):
        sudo('source %s/bin/activate && ./manage.py syncdb --noinput > /dev/null' % env.virtualenv)
        sudo('source %s/bin/activate && ./manage.py migrate --ignore-ghost-migrations' % env.virtualenv)

def switch_symlink():
	notify("Switching symlinks")
	with cd(env.project_dir):
		# Create new symlink for build folder
		sudo('if [ -h current ]; then unlink current; fi' % env)
		sudo('ln -s %(builds_dir)s/%(build_dir)s current' % env)

def deploy_nginx_config():
    notify('Moving nginx config into place')
    with cd(env.code_dir):
        sudo('mv %(nginx_conf)s /etc/nginx/conf.d/%(project_code)s.conf' % env)

def reload_python_code():
	notify('Touching WSGI file to reload python code')
	with cd(env.builds_dir):
		sudo('if [ -h %(available_wsgi)s ]; then unlink %(available_wsgi)s; fi' % env)
		sudo('ln -s %(project_dir)s/current/%(wsgi)s %(available_wsgi)s' % env)
		sudo('touch %(enabled_wsgi)s' % env)

def reload_nginx():
    notify('Reloading nginx configuration')
    sudo('/etc/init.d/nginx force-reload')

def delete_old_builds():
    notify('Deleting old builds')
    with cd(env.builds_dir):
        sudo('find . -maxdepth 1 -type d -name "%(build)s*" | sort -r | sed "1,9d" | xargs rm -rf' % env)

def custom():
	with cd(env.project_dir):
		notify('Fixing things')
		sudo('if [ -h current/db.sqlite3 ]; then unlink current/db.sqlite3; fi' % env)
		sudo('ln -s /var/web/apps/food/db.sqlite3 current/')
		
		sudo('chown uwsgi:uwsgi current')
		sudo('chown uwsgi:uwsgi current/db.sqlite3')
