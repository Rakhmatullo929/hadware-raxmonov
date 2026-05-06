from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse

from .decorators import role_required


def root(request):
    if request.user.is_authenticated:
        return HttpResponseRedirect(reverse('dashboard'))
    return HttpResponseRedirect(reverse('login'))


@login_required
def dashboard(request):
    return render(request, 'core/dashboard.html')


@login_required
def rentals(request):
    return render(request, 'core/stub.html', {'title': 'Аренды'})


@login_required
def clients(request):
    return render(request, 'core/stub.html', {'title': 'Клиенты'})


@login_required
def products(request):
    return render(request, 'core/stub.html', {'title': 'Товары'})


@role_required('admin')
def reports(request):
    return render(request, 'core/stub.html', {'title': 'Отчёты'})
