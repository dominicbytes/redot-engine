/**************************************************************************/
/*  test_gdextension.h                                                  */
/**************************************************************************/
/*                         This file is part of:                          */
/*                             REDOT ENGINE                               */
/*                        https://redotengine.org                         */
/**************************************************************************/
/* Copyright (c) 2024-present Redot Engine contributors                   */
/*                                          (see REDOT_AUTHORS.md)        */
/* Copyright (c) 2014-present Godot Engine contributors (see AUTHORS.md). */
/* Copyright (c) 2007-2014 Juan Linietsky, Ariel Manzur.                  */
/*                                                                        */
/* Permission is hereby granted, free of charge, to any person obtaining  */
/* a copy of this software and associated documentation files (the        */
/* "Software"), to deal in the Software without restriction, including    */
/* without limitation the rights to use, copy, modify, merge, publish,    */
/* distribute, sublicense, and/or sell copies of the Software, and to     */
/* permit persons to whom the Software is furnished to do so, subject to  */
/* the following conditions:                                              */
/*                                                                        */
/* The above copyright notice and this permission notice shall be         */
/* included in all copies or substantial portions of the Software.        */
/*                                                                        */
/* THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,        */
/* EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF     */
/* MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. */
/* IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY   */
/* CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,   */
/* TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE      */
/* SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.                 */
/**************************************************************************/

#pragma once

#include "core/extension/gdextension.h"
#include "core/variant/struct_info.h"
#include "tests/test_macros.h"

namespace TestGDExtension {

TEST_CASE("[GDExtension] Variant converters cover every non-Nil type") {
	auto from_type = reinterpret_cast<GDExtensionInterfaceGetVariantFromTypeConstructor>(GDExtension::get_interface_function("get_variant_from_type_constructor"));
	auto to_type = reinterpret_cast<GDExtensionInterfaceGetVariantToTypeConstructor>(GDExtension::get_interface_function("get_variant_to_type_constructor"));
	REQUIRE(from_type != nullptr);
	REQUIRE(to_type != nullptr);
	for (int type = GDEXTENSION_VARIANT_TYPE_BOOL; type < GDEXTENSION_VARIANT_TYPE_VARIANT_MAX; type++) {
		CHECK(from_type(static_cast<GDExtensionVariantType>(type)) != nullptr);
		CHECK(to_type(static_cast<GDExtensionVariantType>(type)) != nullptr);
	}
}

TEST_CASE("[GDExtension] Struct converters preserve values and ownership") {
	auto from_type = reinterpret_cast<GDExtensionInterfaceGetVariantFromTypeConstructor>(GDExtension::get_interface_function("get_variant_from_type_constructor"))(GDEXTENSION_VARIANT_TYPE_STRUCT);
	auto to_type = reinterpret_cast<GDExtensionInterfaceGetVariantToTypeConstructor>(GDExtension::get_interface_function("get_variant_to_type_constructor"))(GDEXTENSION_VARIANT_TYPE_STRUCT);
	REQUIRE(from_type != nullptr);
	REQUIRE(to_type != nullptr);

	StructInfoBuilder builder;
	builder.set_logical_type_id("ConverterTest");
	StructInfo::Field field;
	field.name = "value";
	field.default_value = "original";
	builder.add_field(field);
	Ref<StructInfo> info = builder.build();
	REQUIRE(info.is_valid());

	for (bool populated : { false, true }) {
		Struct source = populated ? Struct(info) : Struct();
		alignas(Variant) uint8_t variant_storage[sizeof(Variant)];
		from_type(variant_storage, &source);
		Variant *variant = reinterpret_cast<Variant *>(variant_storage);
		CHECK(variant->get_type() == Variant::STRUCT);
		if (populated) {
			source.set_member(0, "source changed");
			CHECK(static_cast<Struct>(*variant).get_member(0) == Variant("original"));
		}
		alignas(Struct) uint8_t struct_storage[sizeof(Struct)];
		to_type(struct_storage, variant);
		Struct *copy = reinterpret_cast<Struct *>(struct_storage);
		CHECK(*copy == static_cast<Struct>(*variant));
		if (populated) {
			copy->set_member(0, "changed");
			CHECK(static_cast<Struct>(*variant).get_member(0) == Variant("original"));
		}
		variant->~Variant();
		source = Struct();
		if (populated) {
			info.unref();
		}
		CHECK(copy->is_null() == !populated);
		if (populated) {
			CHECK(copy->get_member(0) == Variant("changed"));
		}
		copy->~Struct();
	}
}

} // namespace TestGDExtension
