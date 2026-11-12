import json
from radar.extract import extract_price, parse_price, variant_matches

def test_parse():
    assert parse_price("1.234,56 ₺") == 1234.56
    assert parse_price("400.00") == 400
    assert parse_price("1.500") == 1500
    assert parse_price("₺1.000,00") == 1000
    assert parse_price("85") == 85
    assert parse_price("0.00") is None

def test_variant():
    assert variant_matches("1 Adet", "1 Adet")
    assert not variant_matches("10 Adet", "1 Adet")
    assert not variant_matches("11 adet", "1 adet")
    assert variant_matches("1 kg", "1 kg") and not variant_matches("10 kg", "1 kg")
    assert variant_matches("250 g", "250") and not variant_matches("2500 g", "250")
    assert variant_matches("1 KG", "1 kg")

def test_jsonld_single():
    h = '<script type="application/ld+json">{"@type":"Product","name":"Longan","offers":{"@type":"Offer","priceCurrency":"TRY","price":"199.00","availability":"https://schema.org/OutOfStock"}}</script>'
    r = extract_price(h, "https://x.com/a")
    assert r.price == 199 and r.in_stock is False

def test_jsonld_variants():
    data = {"@type":"Product","name":"Fuerte","offers":[{"@type":"Offer","name":"1 Adet","price":80},{"@type":"Offer","name":"10 Adet","price":740},{"@type":"Offer","name":"20 Adet","price":1445}]}
    h = f'<script type="application/ld+json">{json.dumps(data)}</script>'
    assert extract_price(h, "u", "10 Adet").price == 740
    assert extract_price(h, "u", "1 Adet").price == 80

def test_woocommerce():
    var = [{"attributes":{"attribute_pa_adet":"1-adet"},"display_price":120,"is_in_stock":True},
           {"attributes":{"attribute_pa_adet":"10-adet"},"display_price":1150,"is_in_stock":True}]
    h = f"<form class='variations_form' data-product_variations='{json.dumps(var)}'></form>"
    assert extract_price(h, "https://a.com/p/?attribute_pa_adet=10-adet").price == 1150

def test_nextdata():
    nd = {"props":{"pageProps":{"product":{"variants":[{"title":"500 g","price":195},{"title":"1 kg","price":380}]}}}}
    h = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(nd)}</script>'
    assert extract_price(h, "u", "1 kg").price == 380

def test_html_fallback():
    h = '<div class="product-price"><del>1.200,00 TL</del></div>'
    h = '<span class="price"><ins>1.150,00 ₺</ins></span>'
    assert extract_price(h, "u").price == 1150

def test_meta():
    h = '<meta property="product:price:amount" content="329.00">'
    assert extract_price(h, "u").price == 329

# --- canlı sitelerden görülen yapılar (12.11.2026) ---
def test_woo_stock_label_overrides_jsonld():  # Zahide: JSON-LD InStock ama sayfa "tükendi"
    h = ('<script type="application/ld+json">{"@type":"Product","offers":{"@type":"Offer","price":"170.00","availability":"https://schema.org/InStock"}}</script>'
         '<p class="stock out-of-stock">Stokta yok</p>')
    r = extract_price(h, "u"); assert r.price == 170 and r.in_stock is False

def test_skip_cart_total():  # GSR: önce sepet 0.00 ₺, sonra ürün fiyatı
    h = '<span class="cart-total-price">0.00 ₺</span><div class="price-box">500.00 ₺</div>'
    assert extract_price(h, "u").price == 500

def test_woo_simple_meta_vs_widgets():  # Avokadocu Ayşe: meta doğru, sayfada başka fiyat kutuları var
    h = ('<meta property="product:price:amount" content="450.00">'
         '<div class="summary"><span class="price">360,00 ₺</span><p class="price">450,00 ₺</p></div>')
    assert extract_price(h, "u").price == 450

def test_tropikhasat_variants():
    data = {"@type":"Product","offers":[{"@type":"Offer","name":"1 Kg","price":"190.00"},{"@type":"Offer","name":"1.5 Kg","price":"280.00"},{"@type":"Offer","name":"2 Kg","price":"370.00"}]}
    h = f'<script type="application/ld+json">[{json.dumps(data)}]</script>'
    assert extract_price(h, "u", "1 kg").price == 190
    assert extract_price(h, "u", "250").price is None
