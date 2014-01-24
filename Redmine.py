import re
import json
import functools
import urllib, urllib2
import sublime, sublime_plugin, threading
import webbrowser

class RedmineError(Exception):
  pass

def main_thread(callback, *args, **kwargs):
  # sublime.set_timeout gets used to send things onto the main thread
  # most sublime.[something] calls need to be on the main thread
  sublime.set_timeout(functools.partial(callback, *args, **kwargs), 0)

def open_in_browser(url, browser = None):
  if not re.search("^https?://", url):
    url = "http://" + url
  try:
    print browser
    webbrowser.get(browser).open_new_tab(url)
  except webbrowser.Error:
    sublime.error_message("[Redmine] Invalid browser command")


class RedmineAPIThread(threading.Thread):
  def __init__(self, method, path, callback = None, data={}, host = '', apikey = ''):
    if re.search("^https?://", host):
      self.host = host
    else:
      self.host = "http://" + host
    self.key = apikey
    self.method = method
    self.path = path
    self.data = data
    self.callback = callback
    threading.Thread.__init__(self)

  def run(self):
    h = {
      "X-Redmine-API-Key": self.key,
      "Content-Type": 'application/json'
    }
    try:
      opener = urllib2.build_opener(urllib2.HTTPHandler)

      if self.method == "GET":
        url = "%s/%s.json?%s" % (self.host, self.path, urllib.urlencode(self.data))
        _data = None
      else:
        url = "%s/%s.json" % (self.host, self.path)
        _data = json.dumps(self.data)
      print "[%s] %s" %(self.method, url)
      req = urllib2.Request(url, _data, headers= h)
      req.get_method = lambda: self.method
      http_file = urllib2.urlopen(req)
      main_thread(self.callback, http_file.read().decode('utf-8'))
    except urllib2.HTTPError as e:
      main_thread(sublime.error_message, "[Redmine] %s (%s)" % (e, url))
    except urllib2.URLError as e:
      main_thread(sublime.error_message, "[Redmine] URLError: %s" % (e))

class RedmineCommand(sublime_plugin.WindowCommand):
  def api_call(self, path, data={}, method="GET", callback=None):
    try:
      s = sublime.load_settings("Redmine.sublime-settings")
      host = s.get('host')
      if len(host) == 0: raise RedmineError("Invalid host name")
      apikey = s.get('apikey')
      if len(apikey) == 0: raise RedmineError("Invalid host name")
      thread = RedmineAPIThread(method, path, callback or self.generic_callback, data, host, apikey)
      thread.start()
    except RedmineError as ex:
      sublime.error_message("[Redmine] %s" % ex)


  def generic_callback(self, output):
    pass

  def quick_panel(self, *args, **kwargs):
    self.window.show_quick_panel(*args, **kwargs)

class ListRedmineStatusesCommand(RedmineCommand):
  def __init__(self, window):
    self.statuses = []
    RedmineCommand.__init__(self, window)

  def run(self):
    if len(self.statuses) == 0:
      self.api_call('issue_statuses')
    else:
      self.select_status()

  def generic_callback(self, output):
    jout = json.loads(output)
    self.statuses = jout['issue_statuses']
    self.select_status()

  def select_status(self):
    self.quick_panel([s['name'] for s in self.statuses], self.status_selected)

  def status_selected(self, idx):
    if idx >= 0:
      sublime.status_message("Selected status: %s" % (self.statuses[idx]['name']))


class ListRedmineIssuesCommand(RedmineCommand):
  def run(self):
    self.api_call('issues', {'sort': 'id:desc'})

  def generic_callback(self, output):
    jout = json.loads(output)
    self.issues = jout['issues']
    self.quick_panel(["#%d: [%s] %s" % (i["id"], i["project"]["name"], i["subject"]) for i in self.issues], self.select_issue)


  def select_issue(self, idx):
    if idx >= 0:
      issue_id = self.issues[idx]['id']
      s = sublime.load_settings("Redmine.sublime-settings")
      host = s.get('host')
      browser = s.get('browser')
      if not isinstance(browser, basestring):
        browser = None
      else:
        browser = str(browser)
      open_in_browser( "%s/issues/%s" % (host, issue_id), browser )


class UpdateRedmineStatusCommand(ListRedmineStatusesCommand):
  def run(self, issue_id):
    if issue_id == None: return

    self.issue_id = issue_id
    ListRedmineStatusesCommand.run(self)


  def status_selected(self, idx):
    # ListRedmineStatusesCommand.status_selected(self, idx)
    if idx >= 0 and self.issue_id != None:

      self.status = self.statuses[idx]

      self.api_call(
        'issues/%s' % self.issue_id,
        {'issue' : {'status_id': self.status['id']}},
        'PUT',
        self.update_response
      )

  def update_response(self, output):
    sublime.status_message("Status of #%s changed to %s" %(self.issue_id, self.status['name']))
  
class UpdateRedmineIssuesCommand(ListRedmineIssuesCommand):
  def select_issue(self, idx):
    if idx >= 0:
      issue_id = self.issues[idx]['id']
      self.window.run_command('update_redmine_status', {'issue_id': issue_id})
