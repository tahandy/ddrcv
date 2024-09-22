import hashlib

def compute_checksum(file_path, algorithm='sha256', chunk_size=4096):
    """Compute the checksum of a large file."""
    hash_algo = hashlib.new(algorithm)

    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(chunk_size), b''):
            hash_algo.update(chunk)

    return hash_algo.hexdigest()


def save_checksum_to_file(checksum, output_file):
    """Save the computed checksum to a file."""
    with open(output_file, 'w') as f:
        f.write(checksum)


def load_checksum_from_file(checksum_file):
    """Load the checksum from a file."""
    with open(checksum_file, 'r') as f:
        return f.read().strip()


def compare_checksums(computed_checksum, loaded_checksum):
    """Compare the computed checksum with the loaded checksum."""
    return computed_checksum == loaded_checksum

