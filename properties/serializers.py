from rest_framework import serializers

from .models import Amenity, Property, PropertyImage


class AmenitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Amenity
        fields = ["id", "name", "icon"]


class PropertyImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = PropertyImage
        fields = ["image", "caption"]


class PropertySummarySerializer(serializers.ModelSerializer):
    """Small embed used inside room responses."""

    class Meta:
        model = Property
        fields = ["id", "name", "slug", "city"]


class PropertyListSerializer(serializers.ModelSerializer):
    amenities = AmenitySerializer(many=True, read_only=True)
    cover_image = serializers.SerializerMethodField()

    class Meta:
        model = Property
        fields = ["id", "name", "slug", "city", "state", "country", "amenities", "cover_image"]

    def get_cover_image(self, obj):
        # .all() uses the prefetch cache; .first() would hit the database per row.
        images = list(obj.images.all())
        if not images:
            return None
        request = self.context.get("request")
        url = images[0].image.url
        return request.build_absolute_uri(url) if request else url


class PropertyDetailSerializer(PropertyListSerializer):
    images = PropertyImageSerializer(many=True, read_only=True)

    class Meta(PropertyListSerializer.Meta):
        fields = PropertyListSerializer.Meta.fields + [
            "description", "address_line", "phone", "email", "timezone",
            "check_in_time", "check_out_time", "free_cancellation_hours",
            "tax_percent", "images",
        ]