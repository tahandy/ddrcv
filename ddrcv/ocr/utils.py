from difflib import SequenceMatcher


def best_string_match(found_string, possible_values):
    best_match = None
    best_similarity = 0
    for true_value in possible_values:
        # Compute similarity using SequenceMatcher
        similarity = SequenceMatcher(None, true_value, found_string).ratio()

        if similarity > best_similarity:
            best_similarity = similarity
            best_match = true_value
    return best_match, best_similarity


def get_best_match_from_results(results, possible_values, lower=True):
    best_match = None
    best_similarity = 0
    for rr in results:
        found_string = rr[1]
        if lower:
            found_string = found_string.lower()

        match, similarity = best_string_match(found_string, possible_values)
        if similarity > best_similarity:
            best_match = match

    return best_match