from pipeline.editorial import terminology_key


def test_acronym_punctuation_is_equivalent_without_losing_vietnamese():
    assert terminology_key('Active galactic nucleus (AGN)') == terminology_key('active galactic nucleus, AGN')
    assert terminology_key('Bồi tụ') == terminology_key('bồi tụ')
    assert terminology_key('bồi tụ') != terminology_key('boi tu')
