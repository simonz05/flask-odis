from __future__ import absolute_import

import odis

from flask.ext.wtf import Form
from wtforms.form import FormMeta
from wtforms import fields, validators

from .fields import (SetMultipleField, SortedSetMultipleField,
        RelMultipleField)

fields_table = {
    'field': fields.StringField,
    'charfield': fields.StringField,
    'integerfield': fields.IntegerField,
    'foreignfield': fields.IntegerField,
    'datetimefield': fields.DateTimeField,
    'datefield': fields.DateField,
    'setfield': SetMultipleField,
    'sortedsetfield': SortedSetMultipleField,
    'relfield': RelMultipleField,
}

def is_coll_field(f):
    return f.__class__.__name__.lower() in ('setfield', 'sortedsetfield', 'relfield')

def formfield_from_modelfield(field):
    field_type = field.__class__.__name__.lower()
    opts = {
        'validators': []
    }

    default = getattr(field, 'default', odis.EMPTY)

    if field_type == 'relfield':
        opts['queryset'] = field.model.obj.all()

    if is_coll_field(field):
        opts['validators'].append(validators.optional())
    elif default != odis.EMPTY or getattr(field, 'nil', False):
        opts['validators'].append(validators.optional())
    else:
        opts['validators'].append(validators.required())

    if default != odis.EMPTY:
        opts['default'] = default

    if getattr(field, 'choices', False):
        opts['choices'] = field.choices

    opts['label'] = field.verbose_name or field.name

    if 'choices' in opts:
        form_field = fields.SelectField
        #opts['coerce'] = field.to_python
    else:
        form_field = fields_table[field_type]

    return form_field(**opts)

def fields_for_model(model, fields=None, exclude=None):
    field_dict = {}

    for name, f in dict(model._fields, **model._coll_fields).items():
        if fields and not name in fields:
            continue

        if exclude and name in exclude:
            continue

        if name in ('pk',):
            continue

        field_dict[name] = formfield_from_modelfield(f)

    return field_dict

class ModelFormOptions(object):
    def __init__(self, options=None):
        self.model = getattr(options, 'model', None)
        self.fields = getattr(options, 'fields', None)
        self.exclude = getattr(options, 'exclude', None)

class ModelFormMeta(FormMeta):
    def __new__(cls, name, bases, attrs):
        new_cls = FormMeta.__new__(cls, name, bases, attrs)
        opts = new_cls._meta = ModelFormOptions(getattr(new_cls, 'Meta', None))

        if opts.model:
            # find decleared fields
            decleared_fields = {}

            for k, v in attrs.items():
                if hasattr(v, '_formfield'):
                    decleared_fields[k] = v

            # TODO: find decleared fields in bases?
            new_cls.model_fields = fields_for_model(opts.model, opts.fields, opts.exclude)

            for name, f in dict(new_cls.model_fields, **decleared_fields).items():
                setattr(new_cls, name, f)

        return new_cls

class ModelForm(Form):
    __metaclass__ = ModelFormMeta

    def __init__(self, *args, **kwargs):
        super(ModelForm, self).__init__(*args, **kwargs)
        self._obj = kwargs.get('obj' or None)

        if self._obj:
            for k in self.coll_fields_iter():
                query = getattr(self._obj, k, None)
                field = getattr(self, k)

                if not getattr(field, 'choices', None):
                    field.choices = ((o, o) for o in query.all())

    def validate(self, *args, **kwargs):
        if not super(ModelForm, self).validate(*args, **kwargs):
            return False

        if not self._obj:
            self._obj = self._meta.model()

        self.populate_obj(self._obj)

        ok = self._obj.is_valid(fields=self.model_fields)
        self._errors = self._obj.errors

        for k, v in self._errors.items():
            if k in self._fields:
                self._fields[k].errors = (v,)
            else:
                # todo, add to __all__
                pass

        return ok

    def populate_obj(self, obj):
        super(ModelForm, self).populate_obj(obj)

    def coll_fields_iter(self):
        'find all coll_fields for the current form'
        for k in self.model_fields:
            if k in self._obj._coll_fields:
                yield self._fields[k]

    def save(self, commit=True):
        if self._errors:
            raise ValueError("Could not save because form didn't validate")

        if not self._obj:
            self._obj = self._meta.model()

        self.populate_obj(self._obj)

        if commit:
            self._obj.save()
            self.save_coll()

        return self._obj

    def save_coll(self):
        for k in self.coll_fields_iter():
            f_type = self._obj._coll_fields.get(k, None)
            f = getattr(self._obj, k, None)
            data = getattr(self._obj, '_' + k + '_data', None)

            if isinstance(f_type, odis.SetField):
                f.replace(*data)
            elif isinstance(f_type, odis.SortedSetField):
                for o in data:
                    f.add(o)
                    # TODO what about score?
            elif isinstance(f_type, odis.RelField):
                f.replace(*(f_type.model.obj.get(pk=o) for o in data))

        return self._obj
