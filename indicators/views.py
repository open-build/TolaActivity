from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.http import HttpResponseRedirect
from .models import Indicator, DisaggregationLabel, DisaggregationValue, CollectedData, IndicatorType, Level, ExternalServiceRecord, ExternalService, TolaTable
from activitydb.models import Program, SiteProfile, Country, Sector, TolaSites, TolaUser, FormGuidance
from django.shortcuts import render_to_response
from django.contrib import messages
from tola.util import getCountry, get_table
from tables import IndicatorTable, IndicatorDataTable
from django_tables2 import RequestConfig
from activitydb.forms import FilterForm
from .forms import IndicatorForm, CollectedDataForm

from django.db.models import Count, Sum
from django.db.models import Q
from django.views.generic.edit import CreateView, UpdateView, DeleteView
from django.views.generic.list import ListView
from django.views.generic.detail import View
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import user_passes_test
from django.core.exceptions import PermissionDenied

from activitydb.mixins import AjaxableResponseMixin
import json

import requests
from export import IndicatorResource, CollectedDataResource


def group_excluded(*group_names, **url):
    """
    If user is in the group passed in permission denied
    :param group_names:
    :param url:
    :return: Bool True or False is users passes test
    """
    def in_groups(u):
        if u.is_authenticated():
            if not bool(u.groups.filter(name__in=group_names)):
                return True
            raise PermissionDenied
        return False
    return user_passes_test(in_groups)


class IndicatorList(ListView):
    """
    Main Indicator Home Page, displays a list of Indicators Filterable by Program
    """
    model = Indicator
    template_name = 'indicators/indicator_list.html'

    def get(self, request, *args, **kwargs):

        countries = getCountry(request.user)
        getPrograms = Program.objects.all().filter(country__in=countries, funding_status="Funded").distinct()

        if int(self.kwargs['pk']) == 0:
            getProgramsIndicator = Program.objects.all().filter(funding_status="Funded", country__in=countries).order_by('name').annotate(indicator_count=Count('indicator'))
        else:
            getProgramsIndicator = Program.objects.all().filter(id=self.kwargs['pk']).order_by('name').annotate(indicator_count=Count('indicator'))

        return render(request, self.template_name, {'getPrograms': getPrograms, 'getProgramsIndicator': getProgramsIndicator})


def import_indicator(service=1,deserialize=True):
    """
    Import a indicators from a web service (the dig only for now)
    :param service:
    :param deserialize:
    :return:
    """
    service = ExternalService.objects.get(id=service)
    #hard code the path to the file for now
    #get_json = open(settings.SITE_ROOT + '/fixtures/dig-indicator-feed.json')
    #print service.feed_url
    response = requests.get(service.feed_url)

    if deserialize == True:
        data = json.loads(response.content) # deserialises it
    else:
        #send json data back not deserialized data
        data = response
    #debug the json data string uncomment dump and print
    #data2 = json.dumps(json_data) # json formatted string
    #print data2

    return data


def indicator_create(request, id=0):
    """
    Create an Indicator with a service template first, or custom.  Step one in Inidcator creation.
    Passed on to IndicatorCreate to do the creation
    :param request:
    :param id:
    :return:
    """
    getIndicatorTypes = IndicatorType.objects.all()
    getCountries = Country.objects.all()
    countries = getCountry(request.user)
    country_id = Country.objects.get(country=countries[0]).id
    getPrograms = Program.objects.all().filter(funding_status="Funded",country__in=countries).distinct()
    getServices = ExternalService.objects.all()
    program_id = id

    if request.method == 'POST':
        #set vars from form and get values from user

        type = IndicatorType.objects.get(indicator_type="custom")
        country = Country.objects.get(id=request.POST['country'])
        program = Program.objects.get(id=request.POST['program'])
        service = request.POST['services']
        level = Level.objects.all()[0]
        node_id = request.POST['service_indicator']
        sector = None
        # add a temp name for custom indicators
        name = "Temporary"
        source = None
        definition = None
        external_service_record = None

        #import recursive library for substitution
        import re

        #checkfor service indicator and update based on values
        if node_id != None and int(node_id) != 0:
            getImportedIndicators = import_indicator(service)
            for item in getImportedIndicators:
                if item['nid'] == node_id:
                    getSector, created = Sector.objects.get_or_create(sector=item['sector'])
                    sector=getSector
                    getLevel, created = Level.objects.get_or_create(name=item['level'].title())
                    level=getLevel
                    name=item['title']
                    source=item['source']
                    definition=item['definition']
                    #replace HTML tags if they are in the string
                    definition = re.sub("<.*?>", "", definition)

                    getService = ExternalService.objects.get(id=service)
                    full_url = getService.url + "/" + item['nid']
                    external_service_record = ExternalServiceRecord(record_id=item['nid'],external_service=getService,full_url=full_url)
                    external_service_record.save()
                    getType, created = IndicatorType.objects.get_or_create(indicator_type=item['type'].title())
                    type=getType

        #save form
        new_indicator = Indicator(country=country,sector=sector,name=name,source=source,definition=definition, external_service_record=external_service_record)
        new_indicator.save()
        new_indicator.program.add(program)
        new_indicator.indicator_type.add(type)
        new_indicator.level.add(level)

        latest = new_indicator.id

        #redirect to update page
        messages.success(request, 'Success, Basic Indicator Created!')
        redirect_url = '/indicators/indicator_update/' + str(latest)+ '/'
        return HttpResponseRedirect(redirect_url)

    # send the keys and vars from the json data to the template along with submitted feed info and silos for new form
    return render(request, "indicators/indicator_create.html", {'country_id': country_id, 'program_id':int(program_id),'getCountries':getCountries, 'getPrograms': getPrograms,'getIndicatorTypes':getIndicatorTypes, 'getServices': getServices})


class IndicatorCreate(CreateView):
    """
    Indicator Form for indicators not using a template or service indicator first as well as the post reciever
    for creating an indicator.  Then redirect back to edit view in IndicatorUpdate.
    """
    model = Indicator
    template_name = 'indicators/indicator_form.html'

    try:
        guidance = FormGuidance.objects.get(form="Indicator")
    except FormGuidance.DoesNotExist:
        guidance = None

    #pre-populate parts of the form
    def get_initial(self):
        user_profile = TolaUser.objects.get(user=self.request.user)
        initial = {
            'country': user_profile.country,
            'program': self.kwargs['id'],
            }

        return initial

    def get_context_data(self, **kwargs):
        context = super(IndicatorCreate, self).get_context_data(**kwargs)
        context.update({'id': self.kwargs['id']})
        return context

    @method_decorator(group_excluded('ViewOnly', url='activitydb/permission'))
    def dispatch(self, request, *args, **kwargs):
        return super(IndicatorCreate, self).dispatch(request, *args, **kwargs)

    # add the request to the kwargs
    def get_form_kwargs(self):
        kwargs = super(IndicatorCreate, self).get_form_kwargs()
        kwargs['request'] = self.request
        program = Indicator.objects.all().filter(id=self.kwargs['pk']).values("program__id")
        kwargs['program'] = program
        return kwargs

    def form_invalid(self, form):

        messages.error(self.request, 'Invalid Form', fail_silently=False)

        return self.render_to_response(self.get_context_data(form=form))

    def form_valid(self, form):
        form.save()
        messages.success(self.request, 'Success, Indicator Created!')
        form = ""
        return self.render_to_response(self.get_context_data(form=form))


    form_class = IndicatorForm


class IndicatorUpdate(UpdateView):
    """
    Update and Edit Indicators.
    """
    model = Indicator
    template_name = 'indicators/indicator_form.html'

    try:
        guidance = FormGuidance.objects.get(form="Indicator")
    except FormGuidance.DoesNotExist:
        guidance = None

    @method_decorator(group_excluded('ViewOnly', url='activitydb/permission'))
    def dispatch(self, request, *args, **kwargs):
        return super(IndicatorUpdate, self).dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super(IndicatorUpdate, self).get_context_data(**kwargs)
        context.update({'id': self.kwargs['pk']})
        #get external service data if any
        try:
            getExternalServiceRecord = ExternalServiceRecord.objects.all().filter(indicator__id=self.kwargs['pk'])
        except ExternalServiceRecord.DoesNotExist:
            getExternalServiceRecord = None
        context.update({'getExternalServiceRecord': getExternalServiceRecord})

        return context

    # add the request to the kwargs
    def get_form_kwargs(self):
        kwargs = super(IndicatorUpdate, self).get_form_kwargs()
        kwargs['request'] = self.request
        program = Indicator.objects.all().filter(id=self.kwargs['pk']).values("program__id")
        kwargs['program'] = program
        return kwargs

    def form_invalid(self, form):
        messages.error(self.request, 'Invalid Form', fail_silently=False)
        return self.render_to_response(self.get_context_data(form=form))

    def form_valid(self, form):
        form.save()

        messages.success(self.request, 'Success, Indicator Updated!')

        if self.request.POST.has_key('_addanother'):
            url = "/indicators/indicator_create/"
            program = self.request.POST['program']
            qs = program + "/"
            return HttpResponseRedirect(''.join((url, qs)))

        return self.render_to_response(self.get_context_data(form=form))

    form_class = IndicatorForm


class IndicatorDelete(DeleteView):
    """
    Delete and Indicator
    """
    model = Indicator
    success_url = '/indicators/home/0/'

    @method_decorator(group_excluded('ViewOnly', url='activitydb/permission'))
    def dispatch(self, request, *args, **kwargs):
        return super(IndicatorDelete, self).dispatch(request, *args, **kwargs)

    def form_invalid(self, form):

        messages.error(self.request, 'Invalid Form', fail_silently=False)

        return self.render_to_response(self.get_context_data(form=form))

    def form_valid(self, form):

        form.save()

        messages.success(self.request, 'Success, Indicator Deleted!')
        return self.render_to_response(self.get_context_data(form=form))

    form_class = IndicatorForm


def indicator_report(request, program=0):
    """
    This is the indicator library report.  List of all indicators across a country or countries filtered by
    program.  Lives in the "Report" navigation.
    URL: indicators/report/0/
    :param request:
    :param program:
    :return:
    """
    countries = getCountry(request.user)
    getPrograms = Program.objects.all().filter(funding_status="Funded", country__in=countries).distinct()

    if int(program) == 0:
        getIndicators = Indicator.objects.all().select_related().filter(country__in=countries)
    else:
        getIndicators = Indicator.objects.all().filter(program__id=program).select_related()

    table = IndicatorTable(getIndicators)
    table.paginate(page=request.GET.get('page', 1), per_page=20)

    if request.method == "GET" and "search" in request.GET:
        #list1 = list()
        #for obj in filtered:
        #    list1.append(obj)
        """
         fields = (indicator_type, name, number, source, definition, disaggregation, baseline, lop_target, means_of_verification, data_collection_method, responsible_person,
                    method_of_analysis, information_use, reporting_frequency, comments, program, sector, approved_by, approval_submitted_by, create_date, edit_date)
        """
        queryset = Indicator.objects.filter(
                                           Q(indicator_type__indicator_type__contains=request.GET["search"]) |
                                           Q(name__contains=request.GET["search"]) | Q(number__contains=request.GET["search"]) |
                                           Q(number__contains=request.GET["search"]) | Q(sector__sector__contains=request.GET["search"]) |
                                           Q(definition__contains=request.GET["search"])
                                          )
        table = IndicatorTable(queryset)

    RequestConfig(request).configure(table)

    # send the keys and vars from the json data to the template along with submitted feed info and silos for new form
    return render(request, "indicators/report.html", {'program': program, 'get_agreements': table, 'getPrograms': getPrograms, 'form': FilterForm(), 'helper': FilterForm.helper})


def programIndicatorReport(request, program=0):
    """
    This is the GRID report or indicator plan for a program.  Shows a simple list of indicators sorted by level
    and number. Lives in the "Indicator" home page as a link.
    URL: indicators/program_report/[program_id]/
    :param request:
    :param program:
    :return:
    """
    program = int(program)
    countries = getCountry(request.user)
    getPrograms = Program.objects.all().filter(funding_status="Funded", country__in=countries).distinct()
    getIndicators = Indicator.objects.all().filter(program__id=program).select_related().order_by('level', 'number')
    getProgram = Program.objects.get(id=program)

    if request.method == "GET" and "search" in request.GET:
        #list1 = list()
        #for obj in filtered:
        #    list1.append(obj)
        """
         fields = (indicator_type, name, number, source, definition, disaggregation, baseline, lop_target, means_of_verification, data_collection_method, responsible_person,
                    method_of_analysis, information_use, reporting_frequency, comments, program, sector, approved_by, approval_submitted_by, create_date, edit_date)
        """
        getIndicators = Indicator.objects.all().filter(
                                           Q(indicator_type__icontains=request.GET["search"]) |
                                           Q(name__icontains=request.GET["search"]) |
                                           Q(number__icontains=request.GET["search"]) |
                                           Q(definition__startswith=request.GET["search"])
                                          ).filter(program__id=program).select_related().order_by('level','number')


    # send the keys and vars from the json data to the template along with submitted feed info and silos for new form
    return render(request, "indicators/grid_report.html", {'getIndicators': getIndicators, 'getPrograms': getPrograms, 'getProgram': getProgram, 'form': FilterForm(), 'helper': FilterForm.helper})


def indicator_data_report(request, id=0, program=0):
    """
    This is the Indicator Visual report for each indicator and program.  Displays a list collected data entries
    and sums it at the bottom.  Lives in the "Reports" navigation.
    URL: indicators/data/[indicator_id]/[program_id]/
    :param request:
    :param id: Indicator ID
    :param program:
    :return:
    """
    countries = getCountry(request.user)
    getPrograms = Program.objects.all().filter(funding_status="Funded", country__in=countries).distinct()
    getIndicators = Indicator.objects.select_related().filter(country__in=countries)
    indicator_name = None
    program_name = None
    q = None

    #Build query based on filters and search
    if int(id) != 0:
        getSiteProfile = Indicator.objects.all().filter(id=id).select_related()
        q = {
            'indicator__id': id
        }
        indicator_name = Indicator.objects.get(id=id).name
    else:
        getSiteProfile = SiteProfile.objects.all().select_related()
        q = {
            'indicator__country__in': countries,
        }

    if int(program) != 0:
        getSiteProfile = SiteProfile.objects.all().filter(projectagreement__program__id=program).select_related()
        program_name = Program.objects.get(id=program).name
        q = {
            'program__id':program,
            'agreement__program__id': program,
        }
        #redress the indicator list based on program
        getIndicators = Indicator.objects.select_related().filter(program=program)

    if request.method == "GET" and "search" in request.GET:
        queryset = CollectedData.objects.filter(**q).filter(
                                           Q(agreement__project_name__contains=request.GET["search"]) |
                                           Q(description__icontains=request.GET["search"]) |
                                           Q(indicator__name__contains=request.GET["search"])
                                          ).select_related()
    else:
        queryset = CollectedData.objects.all().filter(**q).select_related()

    #pass query to table and configure
    table = IndicatorDataTable(queryset)
    table.paginate(page=request.GET.get('page', 1), per_page=20)

    RequestConfig(request).configure(table)

    # send the keys and vars from the json data to the template along with submitted feed info and silos for new form
    return render(request, "indicators/data_report.html", {'getQuantitativeData':queryset,'countries':countries, 'getSiteProfile':getSiteProfile, 'table': table,'getPrograms':getPrograms, 'getIndicators': getIndicators, 'form': FilterForm(), 'helper': FilterForm.helper, 'id': id,'program':program,'indicator_name':indicator_name, 'program_name': program_name})


class IndicatorReportData(View, AjaxableResponseMixin):
    """
    Indicator based report view
    """

    def get(self, request):

        indicator = Indicator.objects.all().values('id','program__name','program__id','name', 'indicator_type__indicator_type', 'sector__sector','strategic_objectives','level__name','lop_target','baseline','collecteddata','key_performance_indicator')
        indicator_count = Indicator.objects.all().filter(collecteddata__isnull=True).count()
        indicator_data_count = Indicator.objects.all().filter(collecteddata__isnull=False).count()

        indicator_serialized = json.dumps(list(indicator))

        final_dict = {
            'indicator': indicator_serialized,
            'indicator_count': indicator_count,
            'data_count': indicator_data_count
        }

        if request.GET.get('export'):
            indicator_export = Indicator.objects.all().filter(**indicator_filter)
            dataset = IndicatorResource().export(indicator_export)
            response = HttpResponse(dataset.csv, content_type='application/ms-excel')
            response['Content-Disposition'] = 'attachment; filename=indicator_data.csv'
            return response

        return JsonResponse(final_dict, safe=False)


class CollectedDataList(ListView):
    """
    CollectedData List
    """
    model = CollectedData
    template_name = 'indicators/collecteddata_list.html'

    def get(self, request, *args, **kwargs):

        countries = getCountry(request.user)
        getPrograms = Program.objects.all().filter(funding_status="Funded", country__in=countries).distinct()
        getIndicators = Indicator.objects.all().filter(country__in=countries).exclude(collecteddata__isnull=True)
        getCollectedData = None
        collected_sum = None

        #filter by program or inidcator or both
        if int(self.kwargs['indicator']) != 0:
            getCollectedData = CollectedData.objects.all().prefetch_related('evidence','indicator','program','indicator__objectives','indicator__strategic_objectives').filter(indicator__id=self.kwargs['indicator']).order_by('program','indicator__number')
            collected_sum = CollectedData.objects.filter(indicator__id=self.kwargs['indicator']).aggregate(Sum('targeted'),Sum('achieved'))
        elif int(self.kwargs['indicator']) == 0 and int(self.kwargs['program']) != 0:
            getCollectedData = CollectedData.objects.all().prefetch_related('evidence','indicator','program','indicator__objectives','indicator__strategic_objectives').filter(program=self.kwargs['program']).order_by('program','indicator__number')
            collected_sum = CollectedData.objects.filter(program=self.kwargs['program']).aggregate(Sum('targeted'),Sum('achieved'))
            #redress indicator query based on submitted program
            getIndicators = Indicator.objects.select_related().filter(program=self.kwargs['program']).exclude(collecteddata__isnull=True)
        elif int(self.kwargs['indicator']) != 0 and int(self.kwargs['program']) != 0:
            getCollectedData = CollectedData.objects.all().prefetch_related('evidence','indicator','program','indicator__objectives','indicator__strategic_objectives').filter(program=self.kwargs['program'],indicator__id=self.kwargs['indicator']).order_by('program','indicator__number')
            collected_sum = CollectedData.objects.filter(program=self.kwargs['program'],indicator__id=self.kwargs['indicator']).aggregate(Sum('targeted'),Sum('achieved'))
            #redress indicator query based on submitted program
            getIndicators = Indicator.objects.select_related().filter(program=self.kwargs['program']).exclude(collecteddata__isnull=True)
        elif int(self.kwargs['indicator']) == 0 and int(self.kwargs['program']) == 0:
            getCollectedData = CollectedData.objects.all().prefetch_related('evidence','indicator','program','indicator__objectives','indicator__strategic_objectives').filter(indicator__country__in=countries).order_by('program','indicator__number')
            collected_sum = CollectedData.objects.filter(indicator__country__in=countries).aggregate(Sum('targeted'),Sum('achieved'))


        #get details about the filtered indicator or program
        try:
            filter_indicator = Indicator.objects.get(id=self.kwargs['indicator'])
        except Indicator.DoesNotExist:
            filter_indicator = None

        try:
            filter_program = Program.objects.get(id=self.kwargs['program'])
        except Program.DoesNotExist:
            filter_program = None

        if self.request.GET.get('export'):
            dataset = CollectedDataResource().export(getCollectedData)
            response = HttpResponse(dataset.csv, content_type='application/ms-excel')
            response['Content-Disposition'] = 'attachment; filename=indicator_data.csv'
            return response

        return render(request, self.template_name, {'getCollectedData': getCollectedData, 'getPrograms': getPrograms, 'getIndicators':getIndicators,'filter_program':filter_program,'filter_indicator': filter_indicator, 'collected_sum': collected_sum})


class CollectedDataCreate(CreateView):
    """
    CollectedData Form
    """
    model = CollectedData
    template_name = 'indicators/collecteddata_form.html'
    form_class = CollectedDataForm

    try:
        guidance = FormGuidance.objects.get(form="CollectedData")
    except FormGuidance.DoesNotExist:
        guidance = None

    @method_decorator(group_excluded('ViewOnly', url='activitydb/permission'))
    def dispatch(self, request, *args, **kwargs):
        return super(CollectedDataCreate, self).dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super(CollectedDataCreate, self).get_context_data(**kwargs)
        try:
            getDisaggregationLabel = DisaggregationLabel.objects.all().filter(disaggregation_type__indicator__id=self.kwargs['indicator'])
        except DisaggregationLabel.DoesNotExist:
            getDisaggregationLabel = None

        #set values to None so the form doesn't display empty fields for previous entries
        getDisaggregationValue = None

        context.update({'getDisaggregationValue': getDisaggregationValue})
        context.update({'getDisaggregationLabel': getDisaggregationLabel})
        context.update({'indicator_id': self.kwargs['indicator']})
        context.update({'program_id': self.kwargs['program']})

        return context

    def get_initial(self):
        initial = {
            'indicator': self.kwargs['indicator'],
            'program': self.kwargs['program'],
        }

        return initial

    # add the request to the kwargs
    def get_form_kwargs(self):
        kwargs = super(CollectedDataCreate, self).get_form_kwargs()
        kwargs['request'] = self.request
        kwargs['program'] = self.kwargs['program']

        return kwargs


    def form_invalid(self, form):

        messages.error(self.request, 'Invalid Form', fail_silently=False)

        return self.render_to_response(self.get_context_data(form=form))

    def form_valid(self, form):

        latest = CollectedData.objects.latest('id')
        getCollectedData = CollectedData.objects.get(id=latest.id)
        getDisaggregationLabel = DisaggregationLabel.objects.all().filter(disaggregation_type__indicator__id=self.kwargs['indicator'])

        # update the count with the value of Table unique count
        if form.instance.update_count_tola_table and form.instance.tola_table:
            count = getTableCount(self.request.POST['tola_table'])
            form.instance.achieved = count

        for label in getDisaggregationLabel:
            for key, value in self.request.POST.iteritems():
                if key == label.id:
                    value_to_insert = value
                else:
                    value_to_insert = None
            if value_to_insert:
                insert_disaggregationvalue = DisaggregationValue(dissaggregation_label=label, value=value_to_insert,collecteddata=getCollectedData)
                insert_disaggregationvalue.save()

        form.save()
        messages.success(self.request, 'Success, Data Created!')

        redirect_url = '/indicators/home/0/'
        return HttpResponseRedirect(redirect_url)


class CollectedDataUpdate(UpdateView):
    """
    CollectedData Form
    """
    model = CollectedData
    template_name = 'indicators/collecteddata_form.html'

    try:
        guidance = FormGuidance.objects.get(form="CollectedData")
    except FormGuidance.DoesNotExist:
        guidance = None

    @method_decorator(group_excluded('ViewOnly', url='activitydb/permission'))
    def dispatch(self, request, *args, **kwargs):
        return super(CollectedDataUpdate, self).dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super(CollectedDataUpdate, self).get_context_data(**kwargs)
        #get the indicator_id for the collected data
        getIndicator = CollectedData.objects.get(id=self.kwargs['pk'])
        try:
            getDisaggregationLabel = DisaggregationLabel.objects.all().filter(disaggregation_type__indicator__id=getIndicator.indicator_id)
        except DisaggregationLabel.DoesNotExist:
            getDisaggregationLabel = None

        try:
            getDisaggregationValue = DisaggregationValue.objects.all().filter(collecteddata=self.kwargs['pk'])
        except DisaggregationLabel.DoesNotExist:
            getDisaggregationValue = None

        context.update({'getDisaggregationValue': getDisaggregationValue})
        context.update({'getDisaggregationLabel': getDisaggregationLabel})
        context.update({'id': self.kwargs['pk']})
        context.update({'indicator_id': getIndicator.indicator_id})

        return context

    def form_invalid(self, form):
        messages.error(self.request, 'Invalid Form', fail_silently=False)
        return self.render_to_response(self.get_context_data(form=form))

    # add the request to the kwargs
    def get_form_kwargs(self):
        program = CollectedData.objects.get(id=self.kwargs['pk']).program
        kwargs = super(CollectedDataUpdate, self).get_form_kwargs()
        kwargs['request'] = self.request
        kwargs['program'] = program
        return kwargs

    def form_valid(self, form):

        getCollectedData = CollectedData.objects.get(id=self.kwargs['pk'])
        getDisaggregationLabel = DisaggregationLabel.objects.all().filter(disaggregation_type__indicator__id=self.request.POST['indicator'])
        getIndicator = CollectedData.objects.get(id=self.kwargs['pk'])

        # update the count with the value of Table unique count
        if form.instance.update_count_tola_table and form.instance.tola_table:
            print self.request.POST['tola_table']
            count = getTableCount(self.request.POST['tola_table'])
            form.instance.achieved = count

        # save the form then update manytomany relationships
        form.save()

        # Insert or update disagg values
        for label in getDisaggregationLabel:
            for key, value in self.request.POST.iteritems():
                if key == str(label.id):
                    value_to_insert = value
                    save = getCollectedData.disaggregation_value.create(disaggregation_label=label, value=value_to_insert)
                    getCollectedData.disaggregation_value.add(save.id)

        messages.success(self.request, 'Success, Data Updated!')

        redirect_url = '/indicators/home/0/#hidden-' + str(getIndicator.program.id)
        return HttpResponseRedirect(redirect_url)

    form_class = CollectedDataForm


class CollectedDataDelete(DeleteView):
    """
    CollectedData Delete
    """
    model = CollectedData
    success_url = '/indicators/home/0/'

    @method_decorator(group_excluded('ViewOnly', url='activitydb/permission'))
    def dispatch(self, request, *args, **kwargs):
        return super(CollectedDataDelete, self).dispatch(request, *args, **kwargs)


def getTableCount(table_id):
    """
    Count the number of rowns in a TolaTable
    :param table_id: The TolaTable ID to update count from and return
    :return: count : count of rows from TolaTable
    """
    service = ExternalService.objects.get(name="TolaTables")
    filter_url = service.feed_url + "&id=" + table_id

    # loop over the result table and count the number of records for actuals
    actual_data = get_table(filter_url,count=True)
    count = 0
    if actual_data:
        for item in actual_data:
            count = count + 1

    # update with new count
    TolaTable.objects.filter(table_id = table_id).update(unique_count=count)

    return count


def merge_two_dicts(x, y):
    """
    Given two dictionary Items, merge them into a new dict as a shallow copy.
    :param x: Dict 1
    :param y: Dict 2
    :return: Merge of the 2 Dicts
    """
    z = x.copy()
    z.update(y)
    return z


def collecteddata_import(request):
    """
    Import collected data from Tola Tables
    :param request:
    :return:
    """
    owner = request.user
    service = ExternalService.objects.get(name="TolaTables")

    # add filter to get just the users tables only
    user_filter_url = service.feed_url + "&owner__username=" + str(owner)
    shared_filter_url = service.feed_url + "&shared__username=" + str(owner)
    token = TolaSites.objects.get(site_id=1)
    if token.tola_tables_token:
        headers = {'content-type': 'application/json',
               'Authorization': 'Token ' + token.tola_tables_token}
    else:
        headers = {'content-type': 'application/json'}
        print "Token Not Found"

    response = requests.get(user_filter_url, headers=headers, verify=False)
    response2 = requests.get(shared_filter_url, headers=headers, verify=False)

    user_json = json.loads(response.content)
    shared_json = json.loads(response2.content)

    if type(shared_json) is not dict:
        data = user_json + shared_json
    else:
        data = user_json

    # debug the json data string uncomment dump and print
    # data2 = json.dumps(data) # json formatted string
    # print data2

    if request.method == 'POST':
        id = request.POST['service_table']
        filter_url = service.feed_url + "&id=" + id
        token = TolaSites.objects.get(site_id=1)
        if token.tola_tables_token:
            headers = {'content-type': 'application/json',
                   'Authorization': 'Token ' + token.tola_tables_token}
        else:
            headers = {'content-type': 'application/json'}
            print "Token Not Found"

        response = requests.get(filter_url, headers=headers, verify=False)
        get_json = json.loads(response.content)
        data = get_json
        # Get Data Info
        for item in data:
            name = item['name']
            url = item['data']
            remote_owner = item['owner']['username']

        # loop over the result table and count the number of records for actuals
        actual_data = get_table(item['data'])
        count = 0
        for item in actual_data:
            count = count +1


        # get the users country
        countries = getCountry(request.user)
        check_for_existence = TolaTable.objects.all().filter(name=name,owner=owner)
        if check_for_existence:
            result = "error"
        else:
            create_table = TolaTable.objects.create(name=name,owner=owner,remote_owner=remote_owner,table_id=id,url=url, unique_count=count)
            create_table.country.add(countries[0].id)
            create_table.save()
            result = "success"

        # send result back as json
        message = result
        return HttpResponse(json.dumps(message), content_type='application/json')

    # send the keys and vars from the json data to the template along with submitted feed info and silos for new form
    return render(request, "indicators/collecteddata_import.html", {'getTables': data})


def service_json(service):
    """
    For populating service indicators in dropdown
    :param service: The remote data service
    :return: JSON object of the indicators from the service
    """
    service_indicators = import_indicator(service,deserialize=False)
    return HttpResponse(service_indicators, content_type="application/json")


def collected_data_json(AjaxableResponseMixin, indicator,program):
    """
    Displayed on the Indicator home page as a table of collected data entries related to an indicator
    Called from Indicator "data" button onClick
    :param AjaxableResponseMixin:
    :param indicator:
    :param program:
    :return: List of CollectedData entries and sum of there achieved & Targets as well as related indicator and program
    """
    template_name = 'indicators/collected_data_table.html'
    collecteddata = CollectedData.objects.all().filter(indicator=indicator)
    collected_sum = CollectedData.objects.filter(indicator=indicator).aggregate(Sum('targeted'),Sum('achieved'))
    return render_to_response(template_name, {'collecteddata': collecteddata, 'collected_sum': collected_sum, 'indicator_id': indicator, 'program_id': program})


def program_indicators_json(AjaxableResponseMixin,program):
    """
    Displayed on the Indicator home page as a table of indicators related to a Program
    Called from Program "Indicator" button onClick
    :param AjaxableResponseMixin:
    :param program:
    :return: List of Indicators and the Program they are related to
    """
    template_name = 'indicators/program_indicators_table.html'
    indicators = Indicator.objects.all().filter(program=program).annotate(data_count=Count('collecteddata'))
    return render_to_response(template_name, {'indicators': indicators, 'program_id': program})


def tool(request):
    """
    Placeholder for Indicator planning Tool TBD
    :param request:
    :return:
    """
    return render(request, 'indicators/tool.html')


class IndicatorExport(View):
    """
    Export all indicators to a CSV file
    """
    def get(self, *args, **kwargs ):

        if int(kwargs['id']) == 0:
            del kwargs['id']
        if int(kwargs['program']) == 0:
            del kwargs['program']

        queryset = Indicator.objects.filter(**kwargs)
        print kwargs
        indicator = IndicatorResource().export(queryset)
        response = HttpResponse(indicator.csv, content_type='application/ms-excel')
        response['Content-Disposition'] = 'attachment; filename=indicator.csv'
        return response


class IndicatorDataExport(View):
    """
    Export all indicators to a CSV file
    """
    def get(self, *args, **kwargs ):

        if int(kwargs['indicator']) == 0:
            del kwargs['indicator']
        if int(kwargs['program']) == 0:
            del kwargs['program']

        print kwargs

        queryset = CollectedData.objects.filter(**kwargs)
        dataset = CollectedDataResource().export(queryset)
        response = HttpResponse(dataset.csv, content_type='application/ms-excel')
        response['Content-Disposition'] = 'attachment; filename=indicator_data.csv'
        return response


class CountryExport(View):

    def get(self, *args, **kwargs ):
        country = CountryResource().export()
        response = HttpResponse(country.csv, content_type="csv")
        response['Content-Disposition'] = 'attachment; filename=country.csv'
        return response