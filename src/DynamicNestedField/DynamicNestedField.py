import threading
from collections import OrderedDict
from collections.abc import Mapping
from rest_framework import serializers, viewsets
from rest_framework.fields import get_error_detail, set_value
from rest_framework.fields import SkipField
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError
from rest_framework.relations import PKOnlyObject
from rest_framework.serializers import ListSerializer, BaseSerializer
from rest_framework.settings import api_settings
from rest_framework.utils import model_meta
from rest_framework.validators import UniqueValidator
from rest_framework.fields import empty

_requests = {}


class DynamicNestedMixin(serializers.ModelSerializer):
    class Meta:
        model = None
        fields = []
        # fields_by_condition = {}
        extra_kwargs = {}
        DNM_config = {}
        permission_classes = None
        permission_classes_by_method = {}
        instance_validator = []

    def __init__(self, instance=None, data=empty, request=None, **kwargs):
        super().__init__(instance, data, **kwargs)
        if request:
            self.context['request'] = request
        # if instance is not None:
        #     self.instance_validation(instance)

    def is_valid(self, raise_exception=False):
        DNM_config = {
            "field": {
                "create_new_instance": True,  # default: True
                "can_be_edited": True,  # default: True
                "clear_data": False,  # default: False
                "filter": None,  # default: None
                "serializer": None  # default: None
            }
        }

        self.initial_data_formatter(DNM_config)
        self.nested_initial_data_formatter()
        self.removeNoneValues(self.initial_data)

        res = serializers.ModelSerializer.is_valid(self, raise_exception=False)

        if not res:
            raise Exception(self.errors)

        return res

    def nested_initial_data_formatter(self):  # check if filter_field in the model before use.
        info = model_meta.get_field_info(self.Meta.model)
        temp_initial_data = [i for i in self.initial_data.items()]
        for attr, value in temp_initial_data:
            # if value == []:
            #     continue
            if attr in self.Meta.DNM_config:
                config = self.Meta.DNM_config[attr]
                # attribute is Many2Many:
                if attr in info.relations and info.relations[attr].to_many and config["serializer"] is not None:
                    for i, v in enumerate(value):
                        res = None
                        request_contains_filter = config["filter"] in v if isinstance(v, dict) else False
                        request_contains_id = "id" in v if isinstance(v, dict) else False
                        if isinstance(config["serializer"](), DynamicNestedMixin):  # DNM Serializer
                            # ids.
                            if not isinstance(v, dict):
                                res = self.DNM_ids_validator(attr, v)
                            # data with ids.
                            elif isinstance(v, dict) and request_contains_filter:
                                res = self.DNM_data_with_ids_validator(attr, v)
                            # just data.
                            elif isinstance(v, dict):
                                res = self.data_validator(attr, v)
                        else:  # Not DNM Serializer
                            # ids.
                            if not isinstance(v, dict):
                                res = self.ids_validator(attr, v)
                            # data with ids.
                            elif isinstance(v, dict) and request_contains_id:
                                res = self.data_with_ids_validator(attr, v)
                            # just data.
                            elif isinstance(v, dict):
                                res = self.data_validator(attr, v)
                        self.reformat(attr, res, is_many=True, i=i)
                # attribute is ForeignKey:
                elif attr in info.relations and info.relations[attr].to_field is not None and config["serializer"]:
                    res = None
                    request_contains_filter = config["filter"] in value if isinstance(value, dict) else False
                    request_contains_id = "id" in value if isinstance(value, dict) else False
                    if isinstance(config["serializer"](), DynamicNestedMixin):  # DNM Serializer
                        if isinstance(value, (int, str, bool, float)):
                            res = self.DNM_ids_validator(attr, value)
                        elif isinstance(value, dict) and request_contains_filter:
                            res = self.DNM_data_with_ids_validator(attr, value)
                        elif isinstance(value, dict):
                            res = self.data_validator(attr, value)
                    else:
                        if isinstance(value, (int, str, bool, float)):
                            res = self.ids_validator(attr, value)
                        elif isinstance(value, dict) and request_contains_id:
                            res = self.data_with_ids_validator(attr, value)
                        elif isinstance(value, dict):
                            res = self.data_validator(attr, value)
                    self.reformat(attr, res)
                # attribute is Normal:
                elif attr in info.fields_and_pk:
                    pass
                # attribute is CustomField:
                else:
                    pass

    def DNM_ids_validator(self, attr, value):
        if self.Meta.DNM_config[attr]["filter"] is not None:
            filter_field = self.Meta.DNM_config[attr]["filter"]
            model_serializer = self.Meta.DNM_config[attr]["serializer"]
            model = model_serializer.Meta.model
            res = None
            if model_serializer is not None:
                model_filter = None
                model_filter = model.objects.filter(**{filter_field: value})
                if model_filter is not None and model_filter.exists():
                    ser = model_serializer(model_filter[0])
                    res = ser.data
                else:
                    raise Exception(f'no {filter_field} with value of "{value}" for attribute: {attr}')
            else:
                raise Exception(f"Serializer attribute is not specified in DNM_config for filed: {attr}")
        else:
            raise Exception(f"filter attribute is not specified in DNM_config for attribute: {attr}")

        return res

    def ids_validator(self, attr, value):
        model_serializer = self.Meta.DNM_config[attr]["serializer"]
        model = model_serializer.Meta.model
        res = None
        model_filter = model.objects.filter(**{"id": value})
        if model_filter is not None and model_filter.exists():
            ser = model_serializer(model_filter[0])
            res = ser.data
        else:
            raise Exception(f"no 'id' with value of ({value}) for attribute: {attr}")

        return res

    def DNM_data_with_ids_validator(self, attr, value):
        if self.Meta.DNM_config[attr]["filter"] is not None:
            filter_field = self.Meta.DNM_config[attr]["filter"]
            can_edit_ins = self.Meta.DNM_config[attr]["can_be_edited"]
            model_serializer = self.Meta.DNM_config[attr]["serializer"]
            model = model_serializer.Meta.model
            res = None
            if model_serializer is not None:
                if filter_field in value:
                    model_filter = model.objects.filter(**{filter_field: value[filter_field]})
                    if model_filter.exists():
                        ser = model_serializer(model_filter[0], data=value, partial=self.partial)
                        ser.context["request"] = self.context['request'] if 'request' in self.context else None
                        if ser.is_valid():
                            if isinstance(ser, DynamicNestedMixin):
                                if can_edit_ins:
                                    res = ser.validated_data
                                else:
                                    raise Exception(f'can not update attribute: {attr}')
                            else:
                                raise Exception(f"attribute {attr} is not an instance of DynamicNestedMixin class")
                    else:
                        raise Exception(
                            f"no {filter_field} with value of ({value[filter_field]}) for attribute: {attr}")
                else:
                    raise Exception(f"filter value is not specified in body data for attribute: {attr}")
            else:
                raise Exception(f"Serializer attribute is not specified in DNM_config for filed: {attr}")
        else:
            raise Exception(f"filter attribute is not specified in DNM_config for attribute: {attr}")

        return res

    def data_with_ids_validator(self, attr, value):
        model_serializer = self.Meta.DNM_config[attr]["serializer"]
        model = model_serializer.Meta.model
        res = None
        if "id" in value.keys():
            model_filter = model.objects.filter(**{"id": value["id"]})
            if model_filter is not None and model_filter.exists():
                ser = model_serializer(model_filter[0], data=value, partial=self.partial)
                ser.context["request"] = self.context['request'] if 'request' in self.context else None
                if ser.is_valid():
                    ser.validated_data["id"] = value["id"]
                    res = ser.initial_data
            else:
                raise Exception(f"no 'id' with value of ({value}) for attribute: {attr}")
        else:
            raise Exception(f'can not find sub_attribute: "id" in attr: "{attr}"')

        return res

    def data_validator(self, attr, value):
        model_serializer = self.Meta.DNM_config[attr]["serializer"]
        model = model_serializer.Meta.model
        res = None
        if model_serializer is not None:
            ser = model_serializer(data=value, partial=self.partial)
            ser.context["request"] = self.context['request'] if 'request' in self.context else None
            if ser.is_valid():
                res = ser.validated_data
        else:
            raise Exception(f"Serializer attribute is not specified in DNM_config for filed: {attr}")

        return res

    def reformat(self, attr, new_value, is_many=False, i=None):
        if is_many:
            if new_value is not None:
                self.initial_data[attr][i] = new_value
            else:
                self.initial_data[attr].pop(i)
        else:
            if new_value is not None:
                self.initial_data[attr] = new_value
            else:
                self.initial_data.pop(attr)

    def initial_data_formatter(self, DNM_config):
        # check if DNM_config was declared in Meta class if not create it.
        if "DNM_config" not in self.Meta.__dict__:
            self.Meta.DNM_config = {}
        # check field DNM_config and set default value if it was not set.
        for attr, value in [(attr, value) for attr, value in self.initial_data.items()]:
            if attr not in self.Meta.DNM_config:
                self.Meta.DNM_config[attr] = DNM_config["field"]
            # set id read only to False.
            if attr == "id" and "extra_kwargs" in self.Meta.__dict__:
                self.Meta.extra_kwargs["id"] = {"read_only": False}
            elif attr == "id":
                self.Meta.extra_kwargs = {"id": {"read_only": False}}
            # complete missing configurations.
            for config in DNM_config['field'].keys():
                if config not in self.Meta.DNM_config[attr]:
                    self.Meta.DNM_config[attr][config] = DNM_config['field'][config]
            # set serializers.
            if attr in self.fields.fields and self.Meta.DNM_config[attr]["serializer"] is None:
                field = self.fields.fields[attr]
                # DNM_subclasses = [cls.__name__ for cls in DynamicNestedMixin.__subclasses__()]
                f_ser = type(field) if isinstance(field, serializers.ModelSerializer) else type(field.child) \
                    if isinstance(field, ListSerializer) and isinstance(field.child, serializers.ModelSerializer) \
                    else None
                self.Meta.DNM_config[attr]['serializer'] = f_ser

                if f_ser is None and isinstance(field, BaseSerializer):
                    self.initial_data.pop(attr)

    def set_field_read_only(self, field, value):
        """
        set new value to read_only property for field and its nexted fields.
        """
        if hasattr(field, "read_only") and not(type(field).__name__ == "ReadOnlyField"):
            field.read_only = False
        if hasattr(field, "fields"):
            for f in field.fields.values():
                self.set_field_read_only(f, value)
        elif hasattr(field, "child"):
            self.set_field_read_only(field.child, value)

    def to_representation(self, instance):  # override
        ins = self.instance_validation(instance)
        if ins:
            return self.get_representation(ins)
        else:
            return OrderedDict()

    def get_representation(self, instance):
        """
        Object instance -> Dict of primitive datatypes.
        """
        ret = OrderedDict()
        fields = self._readable_fields

        for field in fields:
            try:
                attribute = field.get_attribute(instance)
            except SkipField:
                continue

            # We skip `to_representation` for `None` values so that fields do
            # not have to explicitly deal with that case.
            #
            # For related fields with `use_pk_only_optimization` we need to
            # resolve the pk value.
            check_for_none = attribute.pk if isinstance(attribute, PKOnlyObject) else attribute
            if check_for_none is None:
                ret[field.field_name] = None
            else:
                ret[field.field_name] = field.to_representation(attribute)
                if isinstance(ret[field.field_name], list):
                    for obj in [r for r in ret[field.field_name]]:
                        if isinstance(obj, OrderedDict) and len(obj) == 0:
                            ret[field.field_name].pop(ret[field.field_name].index(obj))

        return ret

    @property
    def _writable_fields(self):  # override
        for field in self.fields.values():
            if not field.read_only:
                yield field
            elif field.field_name == "id":
                # removing read_only property from id fields.
                field.read_only = False
                yield field

    def to_internal_value(self, data):  # override
        """
        Dict of native values <- Dict of primitive datatypes.
        """
        if not isinstance(data, Mapping):
            message = self.error_messages['invalid'].format(
                datatype=type(data).__name__
            )
            raise ValidationError({
                api_settings.NON_FIELD_ERRORS_KEY: [message]
            }, code='invalid')

        ret = OrderedDict()
        errors = OrderedDict()
        fields = self._writable_fields

        for field in fields:
            validate_method = getattr(self, 'validate_' + field.field_name, None)
            self.set_field_read_only(field, False)  # setting fields to read_only = False
            primitive_value = field.get_value(data)
            try:
                validated_value = field.run_validation(primitive_value)
                if validate_method is not None:
                    validated_value = validate_method(validated_value)
            except ValidationError as exc:
                errors[field.field_name] = exc.detail
            except DjangoValidationError as exc:
                errors[field.field_name] = get_error_detail(exc)
            except SkipField:
                pass
            else:
                set_value(ret, field.source_attrs, validated_value)

        if errors:
            raise ValidationError(errors)

        return ret

    def get_request(self):
        context = getattr(self, "context", None)
        requests = context['request'] if context and 'request' in context.keys() else None
        if requests is None:
            requests = _requests[threading.get_ident()] if threading.get_ident() in _requests else None
        return requests

    # def get_field_names(self, declared_fields, info):  # override
    #     """
    #     check fields_by_condition and set the first fields
    #     with a True value condition to Meta fields var
    #     """
    #     fields_by_condition = getattr(self.Meta, 'fields_by_condition', {})
    #     for cond, fields in fields_by_condition.items():
    #         if isinstance(cond(), BasePermission):
    #             if cond().has_permission(self.get_request(), None):
    #                 setattr(self.Meta, "fields", fields)
    #                 for field in [f for f in declared_fields]:
    #                     if field not in fields:
    #                         declared_fields.pop(field)
    #                 break
    #         else:
    #             if cond:
    #                 setattr(self.Meta, "fields", fields)
    #                 for field in declared_fields:
    #                     if field not in fields.keys():
    #                         declared_fields.pop(field)
    #                 break
    #     return super().get_field_names(declared_fields, info)

    def removeNoneValues(self, data):
        if isinstance(data, dict):
            for attr, value in {d: data[d] for d in data}.items():
                if isinstance(value, dict):
                    self.removeNoneValues(value)
                elif isinstance(value, list):
                    self.removeNoneValues(value)
                elif value is None:
                    data.pop(attr)
        elif isinstance(data, list):
            for value in [d for d in data]:
                if isinstance(value, dict):
                    self.removeNoneValues(value)
                elif isinstance(value, list):
                    self.removeNoneValues(value)
                elif value is None:
                    data.remove(value)

    def run_validation(self, data=empty):
        # override method. remove all UniqueValidator before running validation.
        self.remove_validator(self, UniqueValidator)
        return super().run_validation(data)

    def remove_validator(self, field, validator_to_remove):
        # this function support removing nested validators.
        if hasattr(field, "validators"):
            for validator in field.validators:
                if isinstance(validator, validator_to_remove):
                    field.validators.remove(validator)
        if hasattr(field, "_writable_fields"):
            for subfield in field._writable_fields:
                self.remove_validator(subfield, validator_to_remove)

    def update_and_set_m2m(self, instance, m2m_fields, info):
        for attr, value in m2m_fields:
            field = getattr(instance, attr)  # the field or the attribute that we will update with new data.
            config = self.Meta.DNM_config[attr] if "DNM_config" in self.Meta.__dict__ else {}

            if not config['can_be_edited']:
                raise Exception(f'can not update attribute: "{attr}" when can_be_edited is set to False')

            # clear old data.
            if ("clear_data" in config.keys()) and config["clear_data"]:
                for i in [material.id for material in field.all()]:
                    field.remove(i)

            # set new data.
            filter_field = config['filter']
            for data in value:
                if filter_field in data:  # if filter was in the data then we will search for old data.
                    filtered_data = field.model.objects.filter(**{filter_field: data[filter_field]})
                    if filtered_data.exists():
                        ser = config["serializer"](filtered_data[0], data=data, partial=self.partial)
                        ser.context["request"] = self.context['request'] if 'request' in self.context else None
                        if ser.is_valid():
                            ser.update(ser.instance, data)
                            field.add(ser.instance)
                    else:
                        raise Exception(
                            f"no filtered_field equal to ({filter_field}={data[filter_field]}) for attribute: {attr}"
                        )
                else:
                    # raise Exception(f'no filtered_field declared in the request for attribute: {attr}')
                    if not config['create_new_instance']:
                        raise Exception(
                            f'can not create attribute: "{attr}" when create_new_instance is set to False')
                    serialized_data = config["serializer"](data=data, partial=self.partial)
                    serialized_data.context["request"] = self.context[
                        'request'] if 'request' in self.context else None
                    if serialized_data.is_valid():
                        ins = serialized_data.save()
                        field.add(ins)
                    else:
                        raise Exception(serialized_data.errors)

    def create_and_set_m2m(self, instance, m2m_fields, info):
        for attr, value in m2m_fields:
            field = getattr(instance, attr)  # the field or the attribute that we will update with new data.
            config = self.Meta.DNM_config[attr] if "DNM_config" in self.Meta.__dict__ else {}

            # clear old data.
            if ("clear_data" in config.keys()) and config["clear_data"]:
                for i in [material.id for material in field.all()]:
                    field.remove(i)

            # set new data.
            filter_field = config['filter']
            for data in value:
                if filter_field not in data:
                    if not config['create_new_instance']:
                        raise Exception(f'can not create attribute: "{attr}" when create_new_instance is set to False')
                    serialized_data = config["serializer"](data=data, partial=self.partial)
                    serialized_data.context["request"] = self.context['request'] if 'request' in self.context else None
                    if serialized_data.is_valid():
                        ins = serialized_data.save()
                        field.add(ins)
                    else:
                        raise Exception(serialized_data.errors)
                else:  # if filtered_field is in data then set the data without updating.
                    filtered_data = field.model.objects.filter(**{filter_field: data[filter_field]})
                    if filtered_data.exists():
                        ser = config["serializer"](filtered_data[0], data=data, partial=self.partial)
                        ser.context["request"] = self.context['request'] if 'request' in self.context else None
                        if ser.is_valid():
                            field.add(ser.instance)
                    else:
                        raise Exception(
                            f"no filtered_field equal to ({filter_field}={data[filter_field]}) for attribute: {attr}"
                        )

    def update_and_set_foreign_key(self, instance, fields, info):
        for attr, value in fields:
            field = getattr(instance, attr)  # the field or the attribute that we will update with new data.
            config = self.Meta.DNM_config[attr] if "DNM_config" in self.Meta.__dict__ else {}

            if not config['can_be_edited']:
                raise Exception(f'can not update attribute: "{attr}" when can_be_edited is set to False')

            # set new data.
            filter_field = config['filter']
            if filter_field in value:  # if filter was in the data then we will search for old data.
                field_model = info.relations[attr].related_model if attr in info.relations else None
                filtered_data = field_model.objects.filter(**{filter_field: value[filter_field]})
                if filtered_data is not None and filtered_data.exists():
                    ser = config["serializer"](filtered_data[0], data=value, partial=self.partial)
                    ser.context["request"] = self.context['request'] if 'request' in self.context else None
                    if ser.is_valid():
                        ser.update(ser.instance, value)
                        setattr(instance, attr, ser.instance)
                else:
                    raise Exception(
                        f"no filtered_field equal to ({filter_field}={value[filter_field]}) for attribute: {attr}"
                    )
            else:
                # raise Exception(f'no filtered_field ({value[filter_field]}) for attribute: {attr}')
                if not config['create_new_instance']:
                    raise Exception(f'can not create attribute: "{attr}" when create_new_instance is set to False')
                serialized_data = config["serializer"](data=value, partial=self.partial)
                serialized_data.context["request"] = self.context['request'] if 'request' in self.context else None
                if serialized_data.is_valid():
                    setattr(instance, attr, serialized_data.save())
                else:
                    raise Exception(serialized_data.errors)

    def create_and_set_foreign_key(self, instance, fields, info):
        for attr, value in fields:
            field = getattr(instance, attr)  # the field or the attribute that we will update with new data.
            config = self.Meta.DNM_config[attr] if "DNM_config" in self.Meta.__dict__ else {}

            # set new data.
            filter_field = config['filter']
            if filter_field not in value:
                if not config['create_new_instance']:
                    raise Exception(f'can not create attribute: "{attr}" when create_new_instance is set to False')
                serialized_data = config["serializer"](data=value, partial=self.partial)
                serialized_data.context["request"] = self.context['request'] if 'request' in self.context else None
                if serialized_data.is_valid():
                    setattr(instance, attr, serialized_data.save())
                else:
                    raise Exception(serialized_data.errors)
            else:  # if filtered_field is in data then set the data without updating.
                field_model = info.relations[attr].related_model if attr in info.relations else None
                filtered_data = field_model.objects.filter(**{filter_field: value[filter_field]})
                if filtered_data is not None and filtered_data.exists():
                    ser = config["serializer"](filtered_data[0], data=value, partial=self.partial)
                    ser.context["request"] = self.context['request'] if 'request' in self.context else None
                    if ser.is_valid():
                        setattr(instance, attr, ser.instance)
                else:
                    raise Exception(
                        f"no filtered_field equal to ({filter_field}={value[filter_field]}) for attribute: {attr}"
                    )

    def update_and_set_custom_fields(self, instance, fields, info):
        pass

    def create_and_set_custom_fields(self, instance, fields, info):
        pass

    def update(self, instance, validated_data):
        self.check_permissions()
        info = model_meta.get_field_info(instance)  # information about model data.

        m2m_fields = []
        foreign_key_fields = []
        custom_fields = []
        for attr, value in validated_data.items():  # loop data to set attribute new data and separate other field.
            if attr in info.relations and info.relations[attr].to_many:  # m2m fields.
                m2m_fields.append((attr, value))
            elif attr in info.relations and info.relations[attr].to_field is not None:  # foreign key fields.
                foreign_key_fields.append((attr, value))
            elif attr in info.fields:  # normal fields.
                setattr(instance, attr, value)
            else:  # custom fields.
                custom_fields.append((attr, value))

        self.update_and_set_m2m(instance, m2m_fields, info)
        self.update_and_set_foreign_key(instance, foreign_key_fields, info)
        self.update_and_set_custom_fields(instance, custom_fields, info)

        instance.save()

        return self.instance_validation(instance)

    def create(self, validated_data):
        self.check_permissions()
        info = model_meta.get_field_info(self.Meta.model)  # information about model data.

        m2m_fields = []
        foreign_key_fields = []
        custom_fields = []
        instance = None
        # loop data to separate m2m, foreign key and custom fields.
        for attr, value in [i for i in validated_data.items()]:
            if attr in info.relations and info.relations[attr].to_many:  # m2m fields.
                m2m_fields.append((attr, value))
                validated_data.pop(attr)
            elif attr in info.relations and info.relations[attr].to_field is not None:  # foreign key fields.
                foreign_key_fields.append((attr, value))
                validated_data.pop(attr)
            elif attr in info.fields:  # normal fields.
                continue
            else:  # custom fields.
                custom_fields.append((attr, value))
                validated_data.pop(attr)

        instance = self.Meta.model.objects.create(**validated_data)  # create the main instance.

        if instance is not None:
            self.create_and_set_m2m(instance, m2m_fields, info)
            self.create_and_set_foreign_key(instance, foreign_key_fields, info)
            self.create_and_set_custom_fields(instance, custom_fields, info)
            instance.save()

        return self.instance_validation(instance)

    def check_permissions(self):
        """
        Check if the request should be permitted.
        Raises an appropriate exception if the request is not permitted.
        """
        request = self.context['request']
        vs = NestedModelViewSet()
        vs.serializer_class = self
        vs.check_permissions(request)

    def instance_validation(self, instance):
        request = self.get_request()

        if request is None:
            raise Exception(
                f'can not find request in serializer context for "{self.__class__.__name__}" serializer')

        if hasattr(self.Meta, "instance_validator"):
            for validator in self.Meta.instance_validator:
                instance = validator().validate(instance, request)

        return instance


class GlobalRequestMiddleware(object):

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _requests[threading.get_ident()] = request
        return self.get_response(request)

    def process_exception(self, request, exception):
        raise exception


class NestedModelViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        """
        Instantiates and returns the list of permissions that this view requires.
        """
        serializer = self.get_serializer_class()

        assert hasattr(serializer.Meta, "permission_classes"), (
                "'%s' should have a `permission_classes` var"
                % serializer.__class__.__name__
        )

        assert serializer.Meta.permission_classes is not None, (
                "'%s' should include a `permission_classes` attribute"
                % serializer.__class__.__name__
        )

        try:
            method = serializer.context['request'].method
        except TypeError:
            method = self.request.method

        permission_classes_by_method = getattr(serializer.Meta, "permission_classes_by_method", {})
        try:  # use permission for specific request method(e.g. POST)
            return [permission() for permission in permission_classes_by_method[method]]
        except KeyError:  # else use the main permission_class.
            return [permission() for permission in serializer.Meta.permission_classes]


class BaseInstanceValidator:
    def validate(self, instance, request):
        pass
