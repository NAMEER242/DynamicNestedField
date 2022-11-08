# DynamicNestedField

`DynamicNestedField` is a set of tools used to perform dynamic nested operation on django models without worrying about the problems and authentication leaks that come with it.

## Installation

Install using `pip`...

```
$ pip install DynamicNestedField
```

## Usage & Example

Working with this library is semilunar to using normal serializers, we will create simple project that contains several models with m2m and foreignkey relations...

* model: `A`
  * ManyToMany: model: `B`
    * ForeignKey: model: `C`

### models:

Here we will define three models as following...

```py
from django.db import models


class C(models.Model):
    charfield = models.CharField(max_length=100)


class B(models.Model):
    charfield = models.CharField(max_length=100)
    c = models.ForeignKey(C, on_delete=models.CASCADE, null=True, blank=True)


class A(models.Model):
    charfield = models.CharField(max_length=100)
    b = models.ManyToManyField(B)

```

### Serializers:

And this is the main serializers that we are using to perform all models operations, we will talk about it just in seconds.

```py
class C_Serializer(DynamicNestedMixin):
    class Meta:
        model = C
        fields = ['charfield']
        permission_classes = [IsAuthenticated]  # the general permission class.
        permission_classes_by_method = {
            'GET': [IsAuthenticated],
            'POST': [IsAuthenticated],
            'PUT': [IsAuthenticated],
            'DELETE': [IsAuthenticated],
            # and so on.
        }


class B_Serializer(DynamicNestedMixin):
    c = C_Serializer()

    class Meta:
        model = B
        fields = ['charfield', 'c']
        DNM_config = {  # DNM_config holds all the configuration needed.
            "c": {
                "filter": "id",
            }
        }
        permission_classes = [IsAuthenticated]  # the general permission class.
        permission_classes_by_method = {
            'GET': [IsAuthenticated],
            'POST': [IsAuthenticated],
            'PUT': [IsAuthenticated],
            'DELETE': [IsAuthenticated],
            # and so on.
        }


class A_Serializer(DynamicNestedMixin):
    b = B_Serializer(many=True)  # many=True for m2m.

    class Meta:
        model = A
        fields = ['charfield', 'b']
        DNM_config = {  # DNM_config holds all the configuration needed.
            "b": {
                "filter": "id",
            }
        }
        permission_classes = [IsAuthenticated]  # the general permission class.
        permission_classes_by_method = {
            'GET': [IsAuthenticated],
            'POST': [IsAuthenticated],
            'PUT': [IsAuthenticated],
            'DELETE': [IsAuthenticated],
            # and so on.
        }

```

As you can see we define our serializers as usual, except this time we use three new variables in our Meta class, the first one is `permission_classes` this variable is an instance of djangoRestFramework VewSet class permission_classes variable it does the same thing, takes a list of `BasePermission` classes that can be used to define permissions by using predefined permissions classes or by creating your own.

The second Variable is `permission_classes_by_method` this is the same as the previous `permission_classes` but here we can define a dict var with its keys as request methods (POST, PUT, GET ...) so we can set custom permissions for each one, if you didn't specify a request method here then the library will use the default permissions that are located in `permission_classes`.

Last variable and the most important one is `DNM_config`, here we define all serializer fields configuration
The default options we have in `DNM_config` are as following...

```py
DNM_config = {
            "field": {  # Default Values...
                "create_new_instance": True,  # if you want to perform create operation on this field.
                "can_be_edited": True,  # if you want to perform update operation on this field.
                "clear_data": False,  # if you want to clear field data before updating it (like if it was m2m relation, and you want to clear the data every time you update using this serializer).
                "filter": None,  # the filter field used to get old data of this field from the database (this attribute must be defined). 
                "serializer": None  # you can set a serializer for this field the library will search for it by itself.
            }
        }
```

Here the filter attribute is the only required attribute the rest of them can be removed, and the library will set its default values.

### views:

Last step is defining out ViewSets...

```py
class C_ViewSet(NestedModelViewSet):
    queryset = C.objects.all()
    serializer_class = C_Serializer


class B_ViewSet(NestedModelViewSet):
    queryset = B.objects.all()
    serializer_class = B_Serializer


class A_ViewSet(NestedModelViewSet):
    queryset = A.objects.all()
    serializer_class = A_Serializer

```

As you can see our ViewSets are so brief and simple thanks to the abbreviation of all the operation of the nested models.

### Using The Api

Now we can run the project and try our new api...

#### POST:

```
{
  "charfield": "a",
  "b": [
    {
      "charfield": "b",
      "c": {
        "charfield": "c"
      }
    }
  ]
}
```

This will create model A first and then will start creating model B data and inserting it to field A, and the same thing with model C data.

#### POST: with using old data...

```
{
  "charfield": "a",
  "b": [
    {
      "id": 1
    }
  ]
}
```

or

```
{
  "charfield": "a",
  "b": [1]
}
```

Here we use an old B model data with id=1.

#### PUT & PATCH:

```
{
  "id": 1,
  "charfield": "a_updated_name",
  "b": [
    {
      "charfield": "b",
      "c": {
        "charfield": "c"
      }
    }
  ]
}
```

This will get model A data with id=1 and update it's a var to `a_updated_name` and create new model B data and set it to out A model that we get first.

#### PUT & PATCH: with old data...

```
{
  "id": 1,
  "charfield": "a_updated_name",
  "b": [2]
}
```

Here it will get model A data with id=1 and add new b var data with id=2.

In short, you can...

* you can create nested models that are inside other models.
* you can update models by setting filter attr value (e.g. `id=1`, or `username="nameer"`).
* you can set old models data by using just the filter attr value without specifying attr name (e.g. `m2m_relation_field=[1,2,3]` or `foreignkey_field="nameer"`)

and you can't:

* you can't update old models in create operation.

and that's it for today 😁
