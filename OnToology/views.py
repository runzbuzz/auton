from django.shortcuts import render, render_to_response, redirect
from django.http import HttpResponseRedirect
from mongoengine.django.auth import User
from django.contrib.auth import authenticate, login as django_login, logout as django_logout
from django.http import JsonResponse
from django import forms
from django.template import RequestContext
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.core.urlresolvers import reverse
import settings
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie

import sys
import string
import random
from datetime import datetime
from autoncore import git_magic, add_webhook,ToolUser, webhook_access, update_g, add_collaborator, get_auton_configuration, clone_repo, prepare_log
from autoncore import parse_online_repo_for_ontologies ,update_file ,return_default_log, remove_webhook
from models import *
import requests
import json
import os
import subprocess

import autoncore

from github import Github
from settings import client_id,client_secret, host



sys.stdout = sys.stderr



def get_repos_formatted(the_repos):
    return the_repos
    repos = []
    for orir in the_repos:
        r = {}
        for ke in orir:
            r[ke]  = orir[ke]
        tools = r['monitoring'].split(",")
        monit=""
        for t in tools:   
            keyval = t.split("=")
            if len(keyval) != 2:
                break
            if keyval[1].lower().strip()=='true':
                keyval[1]='Yes'
            else:
                keyval[1]='No'
            print r['url']+" "+keyval[0]+"="+str(keyval[1])
            r[keyval[0].strip()]=keyval[1]
            monit+="=".join(keyval) +","
        r['monitoring'] = monit
        repos.append(r)
    return repos





def home(request):
    print '****** Welcome to home page ********'
    print >> sys.stderr,  '****** Welcome to the error output ******'
    if 'target_repo' in request.GET:
        #print request.GET
        target_repo = request.GET['target_repo']
        webhook_access_url, state = webhook_access(client_id,host+'/get_access_token')
        request.session['target_repo'] = target_repo
        request.session['state'] = state 
        try: 
            repo = Repo.objects.get(url=target_repo)
        except Exception as e:
            print str(e)
            repo = Repo()
            repo.url=target_repo
            repo.save()
            
        if request.user.is_authenticated():
            ouser = OUser.objects.get(email=request.user.email)
            if repo not in ouser.repos:
                ouser.repos.append(repo)
                ouser.save()
        sys.stdout.flush()
        sys.stderr.flush()        
        if '127.0.0.1:8000' not in request.META['HTTP_HOST'] or not settings.test_conf['local']:
            return  HttpResponseRedirect(webhook_access_url)
    sys.stdout.flush()
    sys.stderr.flush()
    repos = get_repos_formatted(Repo.objects.all())
    return render(request,'home.html',{'repos': repos, 'user': request.user })    


def grant_update(request):
    return render_to_response('msg.html',{'msg': 'Magic is done'},context_instance=RequestContext(request))

  
  
  
def get_access_token(request):
    if request.GET['state'] != request.session['state']:
        return render_to_response('msg.html',{'msg':'Error, ; not an ethical attempt' },context_instance=RequestContext(request))
    data = {
        'client_id': client_id,
        'client_secret': client_secret,
        'code': request.GET['code'],
        'redirect_uri': host+'/add_hook'
    }
    res = requests.post('https://github.com/login/oauth/access_token',data=data)
    atts = res.text.split('&')
    d={}
    for att in atts:
        keyv = att.split('=')
        d[keyv[0]] = keyv[1]
    access_token = d['access_token']
    request.session['access_token'] = access_token
    update_g(access_token)
    print 'access_token: '+access_token
    rpy_wh = add_webhook(request.session['target_repo'], host+"/add_hook")
    rpy_coll = add_collaborator(request.session['target_repo'], ToolUser)
    error_msg = ""
    if rpy_wh['status'] == False:
        error_msg+=str(rpy_wh['error'])
        print 'error adding webhook: '+error_msg
    if rpy_coll['status'] == False:
        error_msg+=str(rpy_coll['error'])
        print 'error adding collaborator: '+rpy_coll['error']
    else:
        print 'adding collaborator: '+rpy_coll['msg']
    if error_msg != "":
        if 'Hook already exists on this repository' in error_msg:
            error_msg = 'This repository already watched'
        return render_to_response('msg.html',{'msg':error_msg },context_instance=RequestContext(request))
    return render_to_response('msg.html',{'msg':'webhook attached and user added as collaborator' },context_instance=RequestContext(request))
    


@csrf_exempt
def add_hook(request):
    if settings.TEST:
        print 'We are in test mode'
    try:
        s = str(request.POST['payload'])
        j = json.loads(s,strict=False)
        s = j['repository']['url']+'updated files: '+str(j['head_commit']['modified'])
        cloning_repo = j['repository']['git_url']
        target_repo = j['repository']['full_name']
        user = j['repository']['owner']['email']
        changed_files = j['head_commit']['modified']
        #changed_files+= j['head_commit']['removed']
        changed_files+= j['head_commit']['added']
        if 'Merge pull request' in  j['head_commit']['message'] or 'OnToology Configuration' == j['head_commit']['message']:
            print 'This is a merge request or Configuration push'
            try:
                repo = Repo.objects.get(url=target_repo)
                print 'got the repo'
                repo.last_used = datetime.today()
                repo.save()
                print 'repo saved'
            except DoesNotExist:
                repo = Repo()
                repo.url=target_repo
                repo.save()
            except Exception as e:
                print 'database_exception: '+str(e)
            msg = 'This indicate that this merge request will be ignored'
            if settings.TEST:
                print msg
                return
            else:
                return render_to_response('msg.html',{'msg': msg},context_instance=RequestContext(request))
    except:
        
        msg = 'This request should be a webhook ping'
        if settings.TEST:
            print msg 
            return
        else:
            return render_to_response('msg.html',{'msg': msg},context_instance=RequestContext(request))
    print '##################################################'
    print 'changed_files: '+str(changed_files)
    # cloning_repo should look like 'git@github.com:AutonUser/target.git'
    tar = cloning_repo.split('/')[-2]
    cloning_repo = cloning_repo.replace(tar,ToolUser)
    cloning_repo = cloning_repo.replace('git://github.com/','git@github.com:')
    comm = "python /home/ubuntu/OnToology/OnToology/autoncore.py "
    comm+=' "'+target_repo+'" "'+user+'" "'+cloning_repo+'" '
    for c in changed_files:
        comm+='"'+c+'" '
    if settings.TEST:
        print 'will call git_magic with target=%s, user=%s, cloning_repo=%s, changed_files=%s'%(target_repo, user, cloning_repo, str(changed_files))
        git_magic(target_repo, user, cloning_repo, changed_files)
        return
    else:
        print 'running autoncore code as: '+comm
        subprocess.Popen(comm,shell=True)
        return render_to_response('msg.html',{'msg': ''+s},context_instance=RequestContext(request))




##The below line is for login
def login(request):
    print '******* login *********'
    redirect_url = host+'/login_get_access'
    sec = ''.join([random.choice(string.ascii_letters+string.digits) for _ in range(9)])
    request.session['state'] = sec
    scope = 'admin:org_hook'
    scope+=',admin:org,admin:public_key,admin:repo_hook,gist,notifications,delete_repo,repo_deployment,repo,public_repo,user,admin:public_key'
    redirect_url = "https://github.com/login/oauth/authorize?client_id="+client_id+"&redirect_uri="+redirect_url+"&scope="+scope+"&state="+sec
    return HttpResponseRedirect(redirect_url)



def logout(request):
    print '*** logout ***'
    django_logout(request)
    return HttpResponseRedirect('/')
    #return render_to_response('msg.html',{'msg':'logged out' },context_instance=RequestContext(request))



def login_get_access(request):
    print '*********** login_get_access ************'
    if request.GET['state'] != request.session['state']:
        return render_to_response('msg.html',{'msg':'Error, ; non-ethical attempt' },context_instance=RequestContext(request))
    data = {
        'client_id': client_id,
        'client_secret': client_secret,
        'code': request.GET['code'],
        'redirect_uri': host#host+'/add_hook'
    }
    res = requests.post('https://github.com/login/oauth/access_token',data=data)
    atts = res.text.split('&')
    d={}
    for att in atts:
        keyv = att.split('=')
        d[keyv[0]] = keyv[1]
    access_token = d['access_token']
    request.session['access_token'] = access_token
    print 'access_token: '+access_token
    g = Github(access_token)
    email = g.get_user().email
    if email=='' or type(email) == type(None):
        return render(request,'msg.html',{'msg': 'You have to make you email public and try again'})
    request.session['avatar_url'] = g.get_user().avatar_url
    print 'avatar_url: '+request.session['avatar_url']
    try: 
        user = OUser.objects.get(email=email)
        user.backend = 'mongoengine.django.auth.MongoEngineBackend'
        user.save()
    except:#The password is never important but we set it here because it is required by User class
        print '<%s>'%(email)
        sys.stdout.flush()
        sys.stderr.flush()
        user = OUser.create_user(username=email, password=request.session['state'], email=email)
        user.backend = 'mongoengine.django.auth.MongoEngineBackend'
        user.save()
    #user.backend = 'mongoengine.django.auth.MongoEngineBackend'
    django_login(request, user)
    print 'access_token: '+access_token
    sys.stdout.flush()
    sys.stderr.flush()
    return HttpResponseRedirect('/')








@login_required
def profile(request):
    
    try:
        #pass
        prepare_log(request.user.email)
    except Exception as e:
        print 'profile preparing log error [normal]: '+str(e)
    print '************* profile ************'
    #f=prepare_log('webinterface-'+request.user.email) # I am disabling this for now
    print str(datetime.today())
    ouser = OUser.objects.get(email=request.user.email)
    if 'repo' in request.GET:
        repo = request.GET['repo']
        print 'repo :<%s>'%(repo)
        print 'got the repo'
        #if True:
        try:
            print 'trying to validate repo' 
            hackatt = True
            for repooo  in  ouser.repos:
                if repooo.url == repo:
                    hackatt=False
                    break
            if hackatt: # trying to access a repo that does not belong to the use currently logged in
                return render(request,'msg.html',{'msg': 'This repo is not added, please do so in the main page'})
            print 'try to get abs folder'
            #ontologies_abs_folder = clone_repo('git@github.com:'+repo, request.user.email, dosleep=False)
            #ontologies_abs_folder ='/Users/blakxu/test123/OnToologyTestEnv/temp/ahmad88me@gmail.com'
            #print 'abs folder: '+ontologies_abs_folder
            #ontologies = parse_folder_for_ontologies(ontologies_abs_folder)
            if type(autoncore.g) == type(None):
                print 'access token is: '+request.session['access_token']
                update_g(request.session['access_token'])
            ontologies = parse_online_repo_for_ontologies(repo)
            print 'ontologies: '+str(len(ontologies))
            for o in ontologies:
                for d in o:
                    print d+': '+str(o[d])
            #return_default_log()
            print 'testing redirect'
            #f.close()
            print 'will return the Json'
            #return JsonResponse({'foo': 'bar'})
            html = render(request,'profile_sliders.html',{'ontologies':ontologies}).content
            return JsonResponse({'ontologies':ontologies, 'sliderhtml': html})
            #return render(request,'profile.html',{'repos': get_repos_formatted(ouser.repos), 'ontologies': ontologies})
        #else:
        except Exception as e:
            print 'exception: '+str(e)
#     sys.stdout= sys.__stdout__
#     sys.stderr = sys.__stderr__
    print 'testing redirect'
    #f.close()
    return render(request,'profile.html',{'repos': get_repos_formatted(ouser.repos)})



def update_conf(request):
    print 'inside update_conf'
    #print request.META['csrfmiddlewaretoken']
    if request.method =="GET":
        return render(request,"msg.html",{"msg":"This method expects POST only"})
    indic = '-ar2dtool'
    data = request.POST
    print 'will go to the loop'
    for key  in data:
        print 'inside the loop'
        if indic in key:
            print 'inside the if'
            onto = key[:-len(indic)]
            ar2dtool = data[onto+'-ar2dtool']
            print 'ar2dtool: '+str(ar2dtool)
            widoco = data[onto+'-widoco']
            print 'widoco: '+str(widoco)
            oops =  data[onto+'-oops']
            print 'oops: '+str(oops)
            print 'will call get_conf'
            new_conf = get_conf(ar2dtool,widoco,oops)
            print 'will call update_file'
            onto = 'OnToology'+onto+'/OnToology.cfg'
            update_file(data['repo'],onto,'OnToology Configuration',new_conf)
            print 'returned from update_file'
    print 'will return msg html'
    return JsonResponse({'status': True,'msg': 'successfully'})
    #return render(request,'msg.html',{'msg': 'updated repos'})



def get_conf(ar2dtool,widoco,oops):
    conf = """
[ar2dtool]
enable = %s

[widoco]
enable = %s

[oops]
enable = %s
    """%(str(ar2dtool),str(widoco),str(oops))
    return conf

@login_required
def delete_repo(request):
    repo = request.GET['repo']
    user = OUser.objects.get(email=request.user.email)
    for r in user.repos:
        if r.url == repo:
            try:
                user.update(pull__repos=r)
                user.save()
                remove_webhook(repo, host+"/add_hook")
                return JsonResponse({'status': True})
            except Exception as e:
                return JsonResponse({'status': False,'error': str(e)})
    return JsonResponse({'status': False, 'error': 'You should add this repo first'})





