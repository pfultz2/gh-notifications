import requests, base64, json, os, datetime, tabulate, pickle, collections, timeago
from flask import Flask, session, redirect, url_for, request, render_template

app = Flask(__name__)

__APP_DIR__ = os.path.dirname(os.path.realpath(__file__))

__DATA_DIR__ = os.path.join(__APP_DIR__, 'data')

__SECRET_FILE__ = os.path.join(__DATA_DIR__, '.secret')

if not os.path.exists(__SECRET_FILE__):
    f = open(__SECRET_FILE__, 'wb')
    f.writelines([os.urandom(16)])
    f.close()

app.secret_key = open(__SECRET_FILE__, 'rb').readlines()[0]

def mkdir(p):
    if not os.path.exists(p): os.makedirs(p)
    return p

def parse_date(s):
    return datetime.datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ')

class GithubEvent:
    def __init__(self, data):
        self.data = data

    def get_id(self):
        return self.data['id']

    def get_date(self):
        return parse_date(self.data['created_at'])

    def get_timeago(self):
        return timeago.format(self.get_date(), datetime.datetime.utcnow())

    def get_repo(self):
        return self.data['repo']['name']

    def get_actor(self):
        return self.data['actor']['login']

    def get_avatar(self):
        return self.data['actor']['avatar_url']

    def get_comment(self):
        if 'payload' in self.data:
            if 'comment' in self.data['payload']:
                return self.data['payload']['comment']
        return None


    def get_payload(self):
        if 'payload' in self.data:
            if 'pull_request' in self.data['payload']:
                return self.data['payload']['pull_request']
            if 'issue' in self.data['payload']:
                return self.data['payload']['issue']
        return None

    def get_title(self):
        payload = self.get_payload()
        if payload:
            return payload['title']
        return ''

    def get_url(self):
        comment = self.get_comment()
        if comment:
            return comment['html_url']
        payload = self.get_payload()
        if payload:
            return payload['html_url']
        return self.data['repo']['url']

def group_by_repo(events):
    groups = collections.OrderedDict()
    for event in events:
        if not event.get_repo() in groups:
            groups[event.get_repo()] = []
        groups[event.get_repo()].append(event)
    return groups

def sort_by_date(events):
    result = list(events)
    result.sort(key=lambda x:x.get_date(), reverse=True)
    return result

def event_dates(events):
    return (event.get_date() for event in events)

def latest_event_date(events):
    if len(events) == 0:
        return datetime.datetime.min
    ed = event_dates(events)
    return max(ed)

class GithubNotifications:
    def __init__(self, user=None, token=None):
        self.user = user
        self.token = token
        self.events = {}

    def get_config_path(self, *paths):
        return os.path.join(__DATA_DIR__, *paths)

    def get_event_file(self):
        return self.get_config_path('events')

    def get_login_file(self):
        return self.get_config_path('login')

    def load_events(self):
        if os.path.exists(self.get_event_file()):
            self.events = pickle.load(open(self.get_event_file(), 'rb'))

    def save_events(self):
        mkdir(self.get_config_path())
        pickle.dump(self.events, open(self.get_event_file(), 'wb'))

    def remove_stale_events(self):
        oldest = datetime.datetime.now() - datetime.timedelta(days=90)
        for event_id, event in self.events.items():
            if event.get_date() < oldest:
                del self.events[event_id]

    def get_events(self):
        return self.events.values()

    def get_page(self, page=0):
        params={"page": page}
        headers ={'Authorization': self.token}
        response = requests.get('https://api.github.com/users/{}/received_events'.format(self.user), headers=headers, params=params)
        rate_limit = response.headers['X-RateLimit-Limit']
        rate_limit_remaining = response.headers['X-RateLimit-Remaining']
        if rate_limit_remaining == 0:
            print("Passed rate limit", rate_limit)
        return [GithubEvent(event) for event in response.json()]

    def add_events(self, events):
        for event in events:
            if event.get_id() in self.events:
                continue
            self.events[event.get_id()] = event

    def query_events(self):
        again = True
        page = 0
        last_time = latest_event_date(self.get_events())
        while again and page < 10:
            events = self.get_page(page)
            self.add_events(events)
            latest = latest_event_date(events)
            again = latest > last_time
            page = page + 1

    def group_events(self):
        events = [event for event in self.get_events() if event.get_payload()]
        return group_by_repo(sort_by_date(events))

    def format_events(self):
        headers = ['repo', 'description', 'actor', 'date']
        events = [[event.get_repo(), event.get_title(), event.get_actor(), event.get_timeago()] for event in sort_by_date(self.get_events())]
        return tabulate.tabulate(events, headers=headers, tablefmt="html")

@app.route('/')
def index():
    if not 'username' in session:
        return redirect(url_for('login'))
    gn = GithubNotifications(session['username'], session['token'])
    gn.load_events()
    gn.remove_stale_events()
    gn.query_events()
    gn.save_events()
    return render_template('index.html', groups=gn.group_events())

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        session['username'] = request.form['username']
        session['token'] = base64.b64encode('{}:{}'.format(request.form['username'], request.form['password']).encode()) 
        return redirect(url_for('index'))
    return '''
        <form method="post">
            <p>Username: <input type=text name=username>
            <p>Password: <input type=password name=password>
            <p><input type=submit value=Login>
        </form>
    '''