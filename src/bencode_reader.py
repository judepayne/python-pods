# None of the python bencode libraries offer a bencode structure aware function for
# reading a stream, so this is what this is
import bencodepy as bencode


def read_until_byte(stream, target_byte):
    """Read until we hit the target byte (inclusive)"""
    result = b''
    while True:
        byte = stream.read(1)
        if not byte:
            raise EOFError("Unexpected EOF")
        result += byte
        if byte == target_byte:
            break
    return result

def read_string_content(stream, first_digit):
    """Read the rest of a length-prefixed string after the first digit"""
    result = b''
    length_bytes = first_digit
    
    # Read remaining digits until we hit the ':'
    while True:
        byte = stream.read(1)
        if not byte:
            raise EOFError("Unexpected EOF while reading string length")
        result += byte
        if byte == b':':
            break
        if not byte.isdigit():
            raise ValueError(f"Invalid character in string length: {byte}")
        length_bytes += byte
    
    # Parse the length (length_bytes contains only digits, no colon)
    string_length = int(length_bytes.decode('ascii'))
    string_content = stream.read(string_length)
    if len(string_content) != string_length:
        raise EOFError(f"Expected {string_length} bytes, got {len(string_content)}")
    result += string_content
    
    return result

def read_list_content(stream):
    """Read list content until the closing 'e'"""
    result = b''
    
    while True:
        byte = stream.read(1)
        if not byte:
            raise EOFError("Unexpected EOF in list")
        
        if byte == b'e':  # End of list
            result += byte
            break
        else:
            # Read a complete bencode value starting with this byte
            if byte == b'd':  # Nested dictionary
                result += byte + read_dict_content(stream)
            elif byte == b'l':  # Nested list
                result += byte + read_list_content(stream)
            elif byte == b'i':  # Integer
                result += byte + read_until_byte(stream, b'e')
            elif byte.isdigit():  # String
                result += byte + read_string_content(stream, byte)
            else:
                raise ValueError(f"Invalid bencode character in list: {byte}")
    
    return result

def read_dict_content(stream):
    """Read dictionary content until the closing 'e'"""
    result = b''
    
    while True:
        byte = stream.read(1)
        if not byte:
            raise EOFError("Unexpected EOF in dictionary")
        
        if byte == b'e':  # End of dictionary
            result += byte
            break
        else:
            # Read a complete bencode value starting with this byte
            if byte == b'd':  # Nested dictionary
                result += byte + read_dict_content(stream)
            elif byte == b'l':  # Nested list
                result += byte + read_list_content(stream)
            elif byte == b'i':  # Integer
                result += byte + read_until_byte(stream, b'e')
            elif byte.isdigit():  # String
                result += byte + read_string_content(stream, byte)
            else:
                raise ValueError(f"Invalid bencode character in dict: {byte}")
    
    return result

def read_bencode_value(stream):
    """Read a single bencode value (int, string, list, or dict)"""
    first_byte = stream.read(1)
    if not first_byte:
        return None
    
    if first_byte == b'd':  # Dictionary
        return first_byte + read_dict_content(stream)
    elif first_byte == b'l':  # List  
        return first_byte + read_list_content(stream)
    elif first_byte == b'i':  # Integer
        return first_byte + read_until_byte(stream, b'e')
    elif first_byte.isdigit():  # String
        return first_byte + read_string_content(stream, first_byte)
    else:
        raise ValueError(f"Invalid bencode start: {first_byte}")
    
def bytes_to_strings(obj):
    """Recursively convert bytes to strings in a data structure"""
    if isinstance(obj, bytes):
        return obj.decode('utf-8')
    elif isinstance(obj, dict):
        return {bytes_to_strings(k): bytes_to_strings(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [bytes_to_strings(item) for item in obj]
    else:
        return obj

def read_message_raw(stream):
    """Read a complete bencode message by tracking structure - returns raw bytes"""
    try:
        buffer = read_bencode_value(stream)
        if buffer is None:
            return None
        return buffer
    except EOFError:
        return None

def read_message(stream, transform=None):
    """Read and decode a complete bencode message from stream, returning strings instead of bytes
    
    Args:
        stream: The input stream to read from
        transform: Optional function to apply additional transformation to the decoded result
    
    Returns:
        Decoded and stringified bencode data, optionally transformed
    """
    try:
        # Get raw bencode bytes
        raw_bytes = read_message_raw(stream)
        if raw_bytes is None:
            return None
        
        # Decode bencode to Python objects
        decoded = bencode.decode(raw_bytes)
        
        # Convert bytes to strings recursively
        result = bytes_to_strings(decoded)
        
        # Apply optional transformation
        if transform is not None:
            result = transform(result)
        
        return result
        
    except Exception:
        return None

# Test function
def test_reader():
    """Test the reader with the actual data from your debug output"""
    # Your specific test message
    test_message = "d6:format4:json10:namespacesld4:name12:pod.test-pod4:varsld4:name7:add-oneeeee3:opsd8:shutdowndee7:readersd12:my/other-tag27:pod.test-pod/read-other-tag6:my/tag8:identityee"
    test_bytes = test_message.encode('utf-8')
    
    import io
    import time
    
    stream = io.BytesIO(test_bytes)
    
    print(f"Testing with message: {test_message[:50]}...")
    print(f"Message length: {len(test_message)} characters")
    print(f"First 20 bytes: {test_bytes[:20]}")
    
    try:
        start_time = time.perf_counter()
        result = read_message(stream)
        end_time = time.perf_counter()
        
        read_time_ms = (end_time - start_time) * 1000
        
        if result:
            print("✅ Successfully read and decoded message!")
            print(f"Read time: {read_time_ms:.3f} ms")
            print(f"Decoded result type: {type(result)}")
            print(f"Keys: {list(result.keys()) if isinstance(result, dict) else 'Not a dict'}")
            print(f"String keys (no b'' prefixes): {all(isinstance(k, str) for k in result.keys()) if isinstance(result, dict) else 'N/A'}")
            print(f"Sample decoded data: format='{result.get('format', 'N/A')}'")
            
            # Test with transform function
            def add_metadata(data):
                if isinstance(data, dict):
                    data['_parsed_at'] = 'test_time'
                return data
            
            stream.seek(0)
            start_time = time.perf_counter()
            transformed_result = read_message(stream, transform=add_metadata)
            end_time = time.perf_counter()
            transform_time_ms = (end_time - start_time) * 1000
            
            print(f"Transform test: {transformed_result.get('_parsed_at', 'MISSING') == 'test_time'}")
            print(f"Read+transform time: {transform_time_ms:.3f} ms")
            
            # Test raw reading too
            stream.seek(0)
            start_time = time.perf_counter()
            raw_result = read_message_raw(stream)
            end_time = time.perf_counter()
            raw_time_ms = (end_time - start_time) * 1000
            
            print(f"Raw read time: {raw_time_ms:.3f} ms")
            print(f"Raw bytes length: {len(raw_result)} bytes")
            print(f"Raw matches input: {raw_result == test_bytes}")
            
            # Calculate overhead breakdown
            decode_overhead = read_time_ms - raw_time_ms
            print(f"Decode+stringify overhead: {decode_overhead:.3f} ms")
            
            # Verify we read exactly the right amount
            remaining = stream.read()
            print(f"Remaining bytes: {len(remaining)} (should be 0)")
            
            if raw_result == test_bytes:
                print("🎉 Perfect match! The parser works correctly.")
            else:
                print("⚠️  Raw buffer doesn't match input")
                print(f"Expected: {test_bytes.hex()}")
                print(f"Got:      {raw_result.hex()}")
        else:
            print("❌ Failed to read message (returned None)")
            
    except Exception as e:
        print(f"❌ Error during parsing: {e}")
        import traceback
        traceback.print_exc()