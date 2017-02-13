#!/usr/bin/python3

import praw
import os
import logging.handlers
import time
import sys
import configparser
import signal
import sqlite3
import datetime
import re

### Config ###
LOG_FOLDER_NAME = "logs"
USER_AGENT = "NSFWMulti (by /u/Watchful1)"
OWNER_NAME = "Watchful1"
MULTI_NAME = "topnsfw"
LOOP_TIME = 15*60

### Logging setup ###
LOG_LEVEL = logging.DEBUG
if not os.path.exists(LOG_FOLDER_NAME):
	os.makedirs(LOG_FOLDER_NAME)
LOG_FILENAME = LOG_FOLDER_NAME+"/"+"bot.log"
LOG_FILE_BACKUPCOUNT = 5
LOG_FILE_MAXSIZE = 1024 * 256

log = logging.getLogger("bot")
log.setLevel(LOG_LEVEL)
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s: %(message)s')
log_stderrHandler = logging.StreamHandler()
log_stderrHandler.setFormatter(log_formatter)
log.addHandler(log_stderrHandler)
if LOG_FILENAME is not None:
	log_fileHandler = logging.handlers.RotatingFileHandler(LOG_FILENAME, maxBytes=LOG_FILE_MAXSIZE, backupCount=LOG_FILE_BACKUPCOUNT)
	log_formatter_file = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
	log_fileHandler.setFormatter(log_formatter_file)
	log.addHandler(log_fileHandler)


def logSubreddit(subreddit):
	c = dbConn.cursor()
	result = c.execute('''
		SELECT count(*)
		FROM subreddits
		WHERE Subreddit = ?
	''', (subreddit,))

	if result.fetchone()[0] == 0:
		c.execute('''
			INSERT INTO subreddits
			(Subreddit)
			VALUES (?)
		''', (subreddit,))
	else:
		c.execute('''
			UPDATE subreddits
			SET LastSeen = CURRENT_TIMESTAMP
			WHERE subreddit = ?
		''', (subreddit,))
	dbConn.commit()


def getSubreddits(date):
	c = dbConn.cursor()
	output = c.execute('''
			SELECT Subreddit
			FROM subreddits
			WHERE LastSeen > ?
				AND Blacklisted = 0
		''', (date.strftime("%Y-%m-%d %H:%M:%S"),))

	results = []
	for row in output:
		results.append(row[0])
	return results


def blacklistSubreddit(subreddit):
	c = dbConn.cursor()
	result = c.execute('''
		SELECT count(*)
		FROM subreddits
		WHERE Subreddit = ?
	''', (subreddit,))

	if result.fetchone()[0] == 0:
		c.execute('''
			INSERT INTO subreddits
			(Subreddit, Blacklisted)
			VALUES (?, 1)
		''', (subreddit,))
	else:
		c.execute('''
			UPDATE subreddits
			SET Blacklisted = 1
			WHERE subreddit = ?
		''', (subreddit,))
	dbConn.commit()


def whitelistSubreddit(subreddit):
	c = dbConn.cursor()
	result = c.execute('''
		SELECT count(*)
		FROM subreddits
		WHERE Subreddit = ?
	''', (subreddit,))

	if result.fetchone()[0] == 0:
		c.execute('''
			INSERT INTO subreddits
			(Subreddit, Whitelisted)
			VALUES (?, 1)
		''', (subreddit,))
	else:
		c.execute('''
			UPDATE subreddits
			SET Whitelisted = 1
			WHERE subreddit = ?
		''', (subreddit,))
	dbConn.commit()


def getWhitelist():
	c = dbConn.cursor()
	output = c.execute('''
			SELECT Subreddit
			FROM subreddits
			WHERE Whitelisted = 1
		''')

	results = set()
	for row in output:
		results.add(row[0])
	return results


def signal_handler(signal, frame):
	log.info("Handling interupt")
	dbConn.commit()
	dbConn.close()
	sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)


dbConn = sqlite3.connect("datebase.db")
c = dbConn.cursor()
c.execute('''
	CREATE TABLE IF NOT EXISTS subreddits (
		ID INTEGER PRIMARY KEY AUTOINCREMENT,
		Subreddit VARCHAR(80) NOT NULL,
		LastSeen TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
		Whitelisted BOOLEAN DEFAULT 0,
		Blacklisted BOOLEAN DEFAULT 0,
		UNIQUE (Subreddit)
	)
''')
dbConn.commit()


log.debug("Connecting to reddit")

once = False
debug = False
user = None
if len(sys.argv) >= 2:
	user = sys.argv[1]
	for arg in sys.argv:
		if arg == 'once':
			once = True
		elif arg == 'debug':
			debug = True
else:
	log.error("No user specified, aborting")
	sys.exit(0)

try:
	r = praw.Reddit(
		user
		,user_agent=USER_AGENT)
except configparser.NoSectionError:
	log.error("User "+user+" not in praw.ini, aborting")
	sys.exit(0)

log.info("Logged into reddit as /u/"+str(r.user.me()))
whitelist = getWhitelist()

while True:
	startTime = time.perf_counter()
	log.debug("Starting run")

	for message in r.inbox.unread(limit=100):
		if isinstance(message, praw.models.Message) and str(message.author).lower() == OWNER_NAME.lower():
			for line in message.body.lower().splitlines():
				subs = re.findall('(?: /r/)(\w*)', line)
				if len(subs):
					if line.startswith("whitelist"):
						for sub in subs:
							whitelistSubreddit(sub.lower())
					if line.startswith("blacklist"):
						for sub in subs:
							blacklistSubreddit(sub.lower())
			message.reply("Lists updated")
			log.info("Message processed")
		message.mark_read()

	for submission in r.subreddit('all').hot(limit=200):
		if submission.over_18 or str(submission.subreddit).lower() in whitelist:
			logSubreddit(str(submission.subreddit).lower())

	subreddits = getSubreddits(datetime.datetime.now() - datetime.timedelta(days=30))

	for multi in r.user.multireddits():
		if multi.name == MULTI_NAME:
			multi.update(subreddits=subreddits)

	log.debug("Run complete after: %d", int(time.perf_counter() - startTime))
	if once:
		break
	time.sleep(LOOP_TIME)
