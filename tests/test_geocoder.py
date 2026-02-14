"""Tests for undisorder.geocoder — GPS reverse geocoding."""

from undisorder.geocoder import Geocoder
from undisorder.geocoder import GeocodingMode
from unittest.mock import MagicMock
from unittest.mock import patch


class TestGeocodingMode:
    """Test geocoding mode enum."""

    def test_off(self):
        assert GeocodingMode.OFF.value == "off"

    def test_offline(self):
        assert GeocodingMode.OFFLINE.value == "offline"

    def test_online(self):
        assert GeocodingMode.ONLINE.value == "online"


class TestGeocoderOff:
    """Test geocoder in off mode."""

    def test_returns_none(self):
        gc = Geocoder(GeocodingMode.OFF)
        assert gc.reverse(48.2082, 16.3738) is None


class TestGeocoderOffline:
    """Test geocoder in offline mode (using reverse_geocode)."""

    def test_returns_place_name(self):
        mock_result = [{"city": "Vienna", "country": "Austria"}]
        with patch("undisorder.geocoder.reverse_geocode.search", return_value=mock_result):
            gc = Geocoder(GeocodingMode.OFFLINE)
            result = gc.reverse(48.2082, 16.3738)
        assert result == "Vienna"

    def test_returns_country_if_no_city(self):
        mock_result = [{"city": "", "country": "Austria"}]
        with patch("undisorder.geocoder.reverse_geocode.search", return_value=mock_result):
            gc = Geocoder(GeocodingMode.OFFLINE)
            result = gc.reverse(47.0, 15.0)
        assert result == "Austria"

    def test_returns_none_on_empty_result(self):
        with patch("undisorder.geocoder.reverse_geocode.search", return_value=[{}]):
            gc = Geocoder(GeocodingMode.OFFLINE)
            result = gc.reverse(0.0, 0.0)
        assert result is None

    def test_returns_none_on_exception(self):
        with patch("undisorder.geocoder.reverse_geocode.search", side_effect=Exception("fail")):
            gc = Geocoder(GeocodingMode.OFFLINE)
            result = gc.reverse(48.2, 16.3)
        assert result is None


class TestGeocoderOnline:
    """Test geocoder in online mode (using geopy/Nominatim)."""

    def test_returns_place_name(self):
        mock_location = MagicMock()
        mock_location.raw = {
            "address": {"city": "Berlin", "country": "Germany"}
        }
        mock_geolocator = MagicMock()
        mock_geolocator.reverse.return_value = mock_location

        with patch("undisorder.geocoder.Nominatim", return_value=mock_geolocator):
            gc = Geocoder(GeocodingMode.ONLINE)
            result = gc.reverse(52.5200, 13.4050)
        assert result == "Berlin"

    def test_falls_back_to_town(self):
        mock_location = MagicMock()
        mock_location.raw = {
            "address": {"town": "Hallstatt", "country": "Austria"}
        }
        mock_geolocator = MagicMock()
        mock_geolocator.reverse.return_value = mock_location

        with patch("undisorder.geocoder.Nominatim", return_value=mock_geolocator):
            gc = Geocoder(GeocodingMode.ONLINE)
            result = gc.reverse(47.5622, 13.6493)
        assert result == "Hallstatt"

    def test_falls_back_to_village(self):
        mock_location = MagicMock()
        mock_location.raw = {
            "address": {"village": "Grindelwald", "country": "Switzerland"}
        }
        mock_geolocator = MagicMock()
        mock_geolocator.reverse.return_value = mock_location

        with patch("undisorder.geocoder.Nominatim", return_value=mock_geolocator):
            gc = Geocoder(GeocodingMode.ONLINE)
            result = gc.reverse(46.6244, 8.0413)
        assert result == "Grindelwald"

    def test_returns_country_as_last_resort(self):
        mock_location = MagicMock()
        mock_location.raw = {"address": {"country": "Iceland"}}
        mock_geolocator = MagicMock()
        mock_geolocator.reverse.return_value = mock_location

        with patch("undisorder.geocoder.Nominatim", return_value=mock_geolocator):
            gc = Geocoder(GeocodingMode.ONLINE)
            result = gc.reverse(64.9631, -19.0208)
        assert result == "Iceland"

    def test_returns_none_when_no_result(self):
        mock_geolocator = MagicMock()
        mock_geolocator.reverse.return_value = None

        with patch("undisorder.geocoder.Nominatim", return_value=mock_geolocator):
            gc = Geocoder(GeocodingMode.ONLINE)
            result = gc.reverse(0.0, 0.0)
        assert result is None

    def test_returns_none_on_exception(self):
        mock_geolocator = MagicMock()
        mock_geolocator.reverse.side_effect = Exception("network error")

        with patch("undisorder.geocoder.Nominatim", return_value=mock_geolocator):
            gc = Geocoder(GeocodingMode.ONLINE)
            result = gc.reverse(48.2, 16.3)
        assert result is None


class TestGeocoderCaching:
    """Test that geocoder caches results."""

    def test_offline_caches_results(self):
        mock_search = MagicMock(return_value=[{"city": "Wien", "country": "AT"}])
        with patch("undisorder.geocoder.reverse_geocode.search", mock_search):
            gc = Geocoder(GeocodingMode.OFFLINE)
            gc.reverse(48.2082, 16.3738)
            gc.reverse(48.2082, 16.3738)
        # Should only call the underlying service once
        assert mock_search.call_count == 1

    def test_different_coords_not_cached(self):
        mock_search = MagicMock(return_value=[{"city": "X", "country": "Y"}])
        with patch("undisorder.geocoder.reverse_geocode.search", mock_search):
            gc = Geocoder(GeocodingMode.OFFLINE)
            gc.reverse(48.0, 16.0)
            gc.reverse(52.0, 13.0)
        assert mock_search.call_count == 2
