<qgis version="3.22.0" styleCategories="Symbology|Labeling" labelsEnabled="0"><renderer-v2 attr="CASE &#13;&#10;&#09;WHEN concluido AND (concluido_em &gt; now() - make_interval(days:=3) OR concluido_em IS NULL) THEN 0 -- concluido nos ultimos 3 dias ou data nula&#13;&#10;&#09;WHEN concluido AND (concluido_em &lt;= now() - make_interval(days:=3)) THEN 1 -- concluido ha mais de 3 dias &#13;&#10;&#09;ELSE 2 -- pendente&#13;&#10;END&#13;&#10;" forceraster="0" symbollevels="0" type="categorizedSymbol" enableorderby="0" referencescale="-1">
        <categories>
          <category symbol="0" uuid="{f9e284c0-9de8-410d-835c-b5e1659a673f}" label="Concluido a menos de 3 dias" type="long" render="true" value="0" />
          <category symbol="1" uuid="{f0863af9-6d32-4c9c-922f-b3c299ef731a}" label="Concluido a mais de 3 dias" type="long" render="true" value="1" />
          <category symbol="2" uuid="{7b81f153-baf8-462b-b61c-51cbc6aa6c05}" label="Pendente" type="long" render="true" value="2" />
          <category symbol="3" uuid="{3fb0d2a7-cb48-4a27-a6d4-d820764f490e}" label="" type="string" render="true" value="" />
        </categories>
        <symbols>
          <symbol force_rhr="0" frame_rate="10" clip_to_extent="1" alpha="1" type="fill" name="0" is_animated="0">
            <data_defined_properties>
              <Option type="Map">
                <Option type="QString" name="name" value="" />
                <Option name="properties" />
                <Option type="QString" name="type" value="collection" />
              </Option>
            </data_defined_properties>
            <layer pass="0" class="LinePatternFill" enabled="1" locked="0" id="{e4e3d522-ef55-4c1b-b835-3fdcc09f34ed}">
              <Option type="Map">
                <Option type="QString" name="angle" value="45" />
                <Option type="QString" name="clip_mode" value="during_render" />
                <Option type="QString" name="color" value="68,255,0,255" />
                <Option type="QString" name="coordinate_reference" value="feature" />
                <Option type="QString" name="distance" value="2" />
                <Option type="QString" name="distance_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="distance_unit" value="MM" />
                <Option type="QString" name="line_width" value="0.26" />
                <Option type="QString" name="line_width_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="line_width_unit" value="MM" />
                <Option type="QString" name="offset" value="0" />
                <Option type="QString" name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="offset_unit" value="MM" />
                <Option type="QString" name="outline_width_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="outline_width_unit" value="MM" />
              </Option>
              <data_defined_properties>
                <Option type="Map">
                  <Option type="QString" name="name" value="" />
                  <Option name="properties" />
                  <Option type="QString" name="type" value="collection" />
                </Option>
              </data_defined_properties>
              <symbol force_rhr="0" frame_rate="10" clip_to_extent="1" alpha="1" type="line" name="@0@0" is_animated="0">
                <data_defined_properties>
                  <Option type="Map">
                    <Option type="QString" name="name" value="" />
                    <Option name="properties" />
                    <Option type="QString" name="type" value="collection" />
                  </Option>
                </data_defined_properties>
                <layer pass="0" class="SimpleLine" enabled="1" locked="0" id="{dc0a0445-c1e6-4610-943b-80762d398a5f}">
                  <Option type="Map">
                    <Option type="QString" name="align_dash_pattern" value="0" />
                    <Option type="QString" name="capstyle" value="square" />
                    <Option type="QString" name="customdash" value="5;2" />
                    <Option type="QString" name="customdash_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="customdash_unit" value="MM" />
                    <Option type="QString" name="dash_pattern_offset" value="0" />
                    <Option type="QString" name="dash_pattern_offset_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="dash_pattern_offset_unit" value="MM" />
                    <Option type="QString" name="draw_inside_polygon" value="0" />
                    <Option type="QString" name="joinstyle" value="bevel" />
                    <Option type="QString" name="line_color" value="68,255,0,255" />
                    <Option type="QString" name="line_style" value="solid" />
                    <Option type="QString" name="line_width" value="0.3" />
                    <Option type="QString" name="line_width_unit" value="MM" />
                    <Option type="QString" name="offset" value="0" />
                    <Option type="QString" name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="offset_unit" value="MM" />
                    <Option type="QString" name="ring_filter" value="0" />
                    <Option type="QString" name="trim_distance_end" value="0" />
                    <Option type="QString" name="trim_distance_end_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="trim_distance_end_unit" value="MM" />
                    <Option type="QString" name="trim_distance_start" value="0" />
                    <Option type="QString" name="trim_distance_start_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="trim_distance_start_unit" value="MM" />
                    <Option type="QString" name="tweak_dash_pattern_on_corners" value="0" />
                    <Option type="QString" name="use_custom_dash" value="0" />
                    <Option type="QString" name="width_map_unit_scale" value="3x:0,0,0,0,0,0" />
                  </Option>
                  <data_defined_properties>
                    <Option type="Map">
                      <Option type="QString" name="name" value="" />
                      <Option name="properties" />
                      <Option type="QString" name="type" value="collection" />
                    </Option>
                  </data_defined_properties>
                </layer>
              </symbol>
            </layer>
            <layer pass="0" class="LinePatternFill" enabled="1" locked="0" id="{324779c2-20ec-4670-b590-b4cbacf6cc22}">
              <Option type="Map">
                <Option type="QString" name="angle" value="135" />
                <Option type="QString" name="clip_mode" value="during_render" />
                <Option type="QString" name="color" value="68,255,0,255" />
                <Option type="QString" name="coordinate_reference" value="feature" />
                <Option type="QString" name="distance" value="2" />
                <Option type="QString" name="distance_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="distance_unit" value="MM" />
                <Option type="QString" name="line_width" value="0.26" />
                <Option type="QString" name="line_width_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="line_width_unit" value="MM" />
                <Option type="QString" name="offset" value="0" />
                <Option type="QString" name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="offset_unit" value="MM" />
                <Option type="QString" name="outline_width_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="outline_width_unit" value="MM" />
              </Option>
              <data_defined_properties>
                <Option type="Map">
                  <Option type="QString" name="name" value="" />
                  <Option name="properties" />
                  <Option type="QString" name="type" value="collection" />
                </Option>
              </data_defined_properties>
              <symbol force_rhr="0" frame_rate="10" clip_to_extent="1" alpha="1" type="line" name="@0@1" is_animated="0">
                <data_defined_properties>
                  <Option type="Map">
                    <Option type="QString" name="name" value="" />
                    <Option name="properties" />
                    <Option type="QString" name="type" value="collection" />
                  </Option>
                </data_defined_properties>
                <layer pass="0" class="SimpleLine" enabled="1" locked="0" id="{ee7b2874-64d9-49cb-adf5-d40745d1aa5d}">
                  <Option type="Map">
                    <Option type="QString" name="align_dash_pattern" value="0" />
                    <Option type="QString" name="capstyle" value="square" />
                    <Option type="QString" name="customdash" value="5;2" />
                    <Option type="QString" name="customdash_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="customdash_unit" value="MM" />
                    <Option type="QString" name="dash_pattern_offset" value="0" />
                    <Option type="QString" name="dash_pattern_offset_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="dash_pattern_offset_unit" value="MM" />
                    <Option type="QString" name="draw_inside_polygon" value="0" />
                    <Option type="QString" name="joinstyle" value="bevel" />
                    <Option type="QString" name="line_color" value="68,255,0,255" />
                    <Option type="QString" name="line_style" value="solid" />
                    <Option type="QString" name="line_width" value="0.3" />
                    <Option type="QString" name="line_width_unit" value="MM" />
                    <Option type="QString" name="offset" value="0" />
                    <Option type="QString" name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="offset_unit" value="MM" />
                    <Option type="QString" name="ring_filter" value="0" />
                    <Option type="QString" name="trim_distance_end" value="0" />
                    <Option type="QString" name="trim_distance_end_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="trim_distance_end_unit" value="MM" />
                    <Option type="QString" name="trim_distance_start" value="0" />
                    <Option type="QString" name="trim_distance_start_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="trim_distance_start_unit" value="MM" />
                    <Option type="QString" name="tweak_dash_pattern_on_corners" value="0" />
                    <Option type="QString" name="use_custom_dash" value="0" />
                    <Option type="QString" name="width_map_unit_scale" value="3x:0,0,0,0,0,0" />
                  </Option>
                  <data_defined_properties>
                    <Option type="Map">
                      <Option type="QString" name="name" value="" />
                      <Option name="properties" />
                      <Option type="QString" name="type" value="collection" />
                    </Option>
                  </data_defined_properties>
                </layer>
              </symbol>
            </layer>
            <layer pass="0" class="SimpleLine" enabled="1" locked="0" id="{cf5bdd8e-5509-49e4-996b-6c3133ae5390}">
              <Option type="Map">
                <Option type="QString" name="align_dash_pattern" value="0" />
                <Option type="QString" name="capstyle" value="square" />
                <Option type="QString" name="customdash" value="5;2" />
                <Option type="QString" name="customdash_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="customdash_unit" value="MM" />
                <Option type="QString" name="dash_pattern_offset" value="0" />
                <Option type="QString" name="dash_pattern_offset_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="dash_pattern_offset_unit" value="MM" />
                <Option type="QString" name="draw_inside_polygon" value="0" />
                <Option type="QString" name="joinstyle" value="bevel" />
                <Option type="QString" name="line_color" value="68,255,0,255" />
                <Option type="QString" name="line_style" value="solid" />
                <Option type="QString" name="line_width" value="0.46" />
                <Option type="QString" name="line_width_unit" value="MM" />
                <Option type="QString" name="offset" value="0" />
                <Option type="QString" name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="offset_unit" value="MM" />
                <Option type="QString" name="ring_filter" value="0" />
                <Option type="QString" name="trim_distance_end" value="0" />
                <Option type="QString" name="trim_distance_end_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="trim_distance_end_unit" value="MM" />
                <Option type="QString" name="trim_distance_start" value="0" />
                <Option type="QString" name="trim_distance_start_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="trim_distance_start_unit" value="MM" />
                <Option type="QString" name="tweak_dash_pattern_on_corners" value="0" />
                <Option type="QString" name="use_custom_dash" value="0" />
                <Option type="QString" name="width_map_unit_scale" value="3x:0,0,0,0,0,0" />
              </Option>
              <data_defined_properties>
                <Option type="Map">
                  <Option type="QString" name="name" value="" />
                  <Option name="properties" />
                  <Option type="QString" name="type" value="collection" />
                </Option>
              </data_defined_properties>
            </layer>
          </symbol>
          <symbol force_rhr="0" frame_rate="10" clip_to_extent="1" alpha="0" type="fill" name="1" is_animated="0">
            <data_defined_properties>
              <Option type="Map">
                <Option type="QString" name="name" value="" />
                <Option name="properties" />
                <Option type="QString" name="type" value="collection" />
              </Option>
            </data_defined_properties>
            <layer pass="0" class="LinePatternFill" enabled="1" locked="0" id="{e4e3d522-ef55-4c1b-b835-3fdcc09f34ed}">
              <Option type="Map">
                <Option type="QString" name="angle" value="45" />
                <Option type="QString" name="clip_mode" value="during_render" />
                <Option type="QString" name="color" value="68,255,0,255" />
                <Option type="QString" name="coordinate_reference" value="feature" />
                <Option type="QString" name="distance" value="2" />
                <Option type="QString" name="distance_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="distance_unit" value="MM" />
                <Option type="QString" name="line_width" value="0.26" />
                <Option type="QString" name="line_width_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="line_width_unit" value="MM" />
                <Option type="QString" name="offset" value="0" />
                <Option type="QString" name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="offset_unit" value="MM" />
                <Option type="QString" name="outline_width_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="outline_width_unit" value="MM" />
              </Option>
              <data_defined_properties>
                <Option type="Map">
                  <Option type="QString" name="name" value="" />
                  <Option name="properties" />
                  <Option type="QString" name="type" value="collection" />
                </Option>
              </data_defined_properties>
              <symbol force_rhr="0" frame_rate="10" clip_to_extent="1" alpha="1" type="line" name="@1@0" is_animated="0">
                <data_defined_properties>
                  <Option type="Map">
                    <Option type="QString" name="name" value="" />
                    <Option name="properties" />
                    <Option type="QString" name="type" value="collection" />
                  </Option>
                </data_defined_properties>
                <layer pass="0" class="SimpleLine" enabled="1" locked="0" id="{dc0a0445-c1e6-4610-943b-80762d398a5f}">
                  <Option type="Map">
                    <Option type="QString" name="align_dash_pattern" value="0" />
                    <Option type="QString" name="capstyle" value="square" />
                    <Option type="QString" name="customdash" value="5;2" />
                    <Option type="QString" name="customdash_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="customdash_unit" value="MM" />
                    <Option type="QString" name="dash_pattern_offset" value="0" />
                    <Option type="QString" name="dash_pattern_offset_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="dash_pattern_offset_unit" value="MM" />
                    <Option type="QString" name="draw_inside_polygon" value="0" />
                    <Option type="QString" name="joinstyle" value="bevel" />
                    <Option type="QString" name="line_color" value="68,255,0,255" />
                    <Option type="QString" name="line_style" value="solid" />
                    <Option type="QString" name="line_width" value="0.3" />
                    <Option type="QString" name="line_width_unit" value="MM" />
                    <Option type="QString" name="offset" value="0" />
                    <Option type="QString" name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="offset_unit" value="MM" />
                    <Option type="QString" name="ring_filter" value="0" />
                    <Option type="QString" name="trim_distance_end" value="0" />
                    <Option type="QString" name="trim_distance_end_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="trim_distance_end_unit" value="MM" />
                    <Option type="QString" name="trim_distance_start" value="0" />
                    <Option type="QString" name="trim_distance_start_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="trim_distance_start_unit" value="MM" />
                    <Option type="QString" name="tweak_dash_pattern_on_corners" value="0" />
                    <Option type="QString" name="use_custom_dash" value="0" />
                    <Option type="QString" name="width_map_unit_scale" value="3x:0,0,0,0,0,0" />
                  </Option>
                  <data_defined_properties>
                    <Option type="Map">
                      <Option type="QString" name="name" value="" />
                      <Option name="properties" />
                      <Option type="QString" name="type" value="collection" />
                    </Option>
                  </data_defined_properties>
                </layer>
              </symbol>
            </layer>
            <layer pass="0" class="LinePatternFill" enabled="1" locked="0" id="{324779c2-20ec-4670-b590-b4cbacf6cc22}">
              <Option type="Map">
                <Option type="QString" name="angle" value="135" />
                <Option type="QString" name="clip_mode" value="during_render" />
                <Option type="QString" name="color" value="68,255,0,255" />
                <Option type="QString" name="coordinate_reference" value="feature" />
                <Option type="QString" name="distance" value="2" />
                <Option type="QString" name="distance_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="distance_unit" value="MM" />
                <Option type="QString" name="line_width" value="0.26" />
                <Option type="QString" name="line_width_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="line_width_unit" value="MM" />
                <Option type="QString" name="offset" value="0" />
                <Option type="QString" name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="offset_unit" value="MM" />
                <Option type="QString" name="outline_width_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="outline_width_unit" value="MM" />
              </Option>
              <data_defined_properties>
                <Option type="Map">
                  <Option type="QString" name="name" value="" />
                  <Option name="properties" />
                  <Option type="QString" name="type" value="collection" />
                </Option>
              </data_defined_properties>
              <symbol force_rhr="0" frame_rate="10" clip_to_extent="1" alpha="1" type="line" name="@1@1" is_animated="0">
                <data_defined_properties>
                  <Option type="Map">
                    <Option type="QString" name="name" value="" />
                    <Option name="properties" />
                    <Option type="QString" name="type" value="collection" />
                  </Option>
                </data_defined_properties>
                <layer pass="0" class="SimpleLine" enabled="1" locked="0" id="{ee7b2874-64d9-49cb-adf5-d40745d1aa5d}">
                  <Option type="Map">
                    <Option type="QString" name="align_dash_pattern" value="0" />
                    <Option type="QString" name="capstyle" value="square" />
                    <Option type="QString" name="customdash" value="5;2" />
                    <Option type="QString" name="customdash_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="customdash_unit" value="MM" />
                    <Option type="QString" name="dash_pattern_offset" value="0" />
                    <Option type="QString" name="dash_pattern_offset_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="dash_pattern_offset_unit" value="MM" />
                    <Option type="QString" name="draw_inside_polygon" value="0" />
                    <Option type="QString" name="joinstyle" value="bevel" />
                    <Option type="QString" name="line_color" value="68,255,0,255" />
                    <Option type="QString" name="line_style" value="solid" />
                    <Option type="QString" name="line_width" value="0.3" />
                    <Option type="QString" name="line_width_unit" value="MM" />
                    <Option type="QString" name="offset" value="0" />
                    <Option type="QString" name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="offset_unit" value="MM" />
                    <Option type="QString" name="ring_filter" value="0" />
                    <Option type="QString" name="trim_distance_end" value="0" />
                    <Option type="QString" name="trim_distance_end_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="trim_distance_end_unit" value="MM" />
                    <Option type="QString" name="trim_distance_start" value="0" />
                    <Option type="QString" name="trim_distance_start_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="trim_distance_start_unit" value="MM" />
                    <Option type="QString" name="tweak_dash_pattern_on_corners" value="0" />
                    <Option type="QString" name="use_custom_dash" value="0" />
                    <Option type="QString" name="width_map_unit_scale" value="3x:0,0,0,0,0,0" />
                  </Option>
                  <data_defined_properties>
                    <Option type="Map">
                      <Option type="QString" name="name" value="" />
                      <Option name="properties" />
                      <Option type="QString" name="type" value="collection" />
                    </Option>
                  </data_defined_properties>
                </layer>
              </symbol>
            </layer>
            <layer pass="0" class="SimpleLine" enabled="1" locked="0" id="{cf5bdd8e-5509-49e4-996b-6c3133ae5390}">
              <Option type="Map">
                <Option type="QString" name="align_dash_pattern" value="0" />
                <Option type="QString" name="capstyle" value="square" />
                <Option type="QString" name="customdash" value="5;2" />
                <Option type="QString" name="customdash_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="customdash_unit" value="MM" />
                <Option type="QString" name="dash_pattern_offset" value="0" />
                <Option type="QString" name="dash_pattern_offset_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="dash_pattern_offset_unit" value="MM" />
                <Option type="QString" name="draw_inside_polygon" value="0" />
                <Option type="QString" name="joinstyle" value="bevel" />
                <Option type="QString" name="line_color" value="68,255,0,255" />
                <Option type="QString" name="line_style" value="solid" />
                <Option type="QString" name="line_width" value="0.46" />
                <Option type="QString" name="line_width_unit" value="MM" />
                <Option type="QString" name="offset" value="0" />
                <Option type="QString" name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="offset_unit" value="MM" />
                <Option type="QString" name="ring_filter" value="0" />
                <Option type="QString" name="trim_distance_end" value="0" />
                <Option type="QString" name="trim_distance_end_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="trim_distance_end_unit" value="MM" />
                <Option type="QString" name="trim_distance_start" value="0" />
                <Option type="QString" name="trim_distance_start_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="trim_distance_start_unit" value="MM" />
                <Option type="QString" name="tweak_dash_pattern_on_corners" value="0" />
                <Option type="QString" name="use_custom_dash" value="0" />
                <Option type="QString" name="width_map_unit_scale" value="3x:0,0,0,0,0,0" />
              </Option>
              <data_defined_properties>
                <Option type="Map">
                  <Option type="QString" name="name" value="" />
                  <Option name="properties" />
                  <Option type="QString" name="type" value="collection" />
                </Option>
              </data_defined_properties>
            </layer>
          </symbol>
          <symbol force_rhr="0" frame_rate="10" clip_to_extent="1" alpha="1" type="fill" name="2" is_animated="0">
            <data_defined_properties>
              <Option type="Map">
                <Option type="QString" name="name" value="" />
                <Option name="properties" />
                <Option type="QString" name="type" value="collection" />
              </Option>
            </data_defined_properties>
            <layer pass="0" class="LinePatternFill" enabled="1" locked="0" id="{e4e3d522-ef55-4c1b-b835-3fdcc09f34ed}">
              <Option type="Map">
                <Option type="QString" name="angle" value="45" />
                <Option type="QString" name="clip_mode" value="during_render" />
                <Option type="QString" name="color" value="255,255,255,64" />
                <Option type="QString" name="coordinate_reference" value="feature" />
                <Option type="QString" name="distance" value="2" />
                <Option type="QString" name="distance_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="distance_unit" value="MM" />
                <Option type="QString" name="line_width" value="0.26" />
                <Option type="QString" name="line_width_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="line_width_unit" value="MM" />
                <Option type="QString" name="offset" value="0" />
                <Option type="QString" name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="offset_unit" value="MM" />
                <Option type="QString" name="outline_width_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="outline_width_unit" value="MM" />
              </Option>
              <data_defined_properties>
                <Option type="Map">
                  <Option type="QString" name="name" value="" />
                  <Option name="properties" />
                  <Option type="QString" name="type" value="collection" />
                </Option>
              </data_defined_properties>
              <symbol force_rhr="0" frame_rate="10" clip_to_extent="1" alpha="1" type="line" name="@2@0" is_animated="0">
                <data_defined_properties>
                  <Option type="Map">
                    <Option type="QString" name="name" value="" />
                    <Option name="properties" />
                    <Option type="QString" name="type" value="collection" />
                  </Option>
                </data_defined_properties>
                <layer pass="0" class="SimpleLine" enabled="1" locked="0" id="{dc0a0445-c1e6-4610-943b-80762d398a5f}">
                  <Option type="Map">
                    <Option type="QString" name="align_dash_pattern" value="0" />
                    <Option type="QString" name="capstyle" value="square" />
                    <Option type="QString" name="customdash" value="5;2" />
                    <Option type="QString" name="customdash_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="customdash_unit" value="MM" />
                    <Option type="QString" name="dash_pattern_offset" value="0" />
                    <Option type="QString" name="dash_pattern_offset_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="dash_pattern_offset_unit" value="MM" />
                    <Option type="QString" name="draw_inside_polygon" value="0" />
                    <Option type="QString" name="joinstyle" value="bevel" />
                    <Option type="QString" name="line_color" value="255,255,255,64" />
                    <Option type="QString" name="line_style" value="solid" />
                    <Option type="QString" name="line_width" value="0.3" />
                    <Option type="QString" name="line_width_unit" value="MM" />
                    <Option type="QString" name="offset" value="0" />
                    <Option type="QString" name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="offset_unit" value="MM" />
                    <Option type="QString" name="ring_filter" value="0" />
                    <Option type="QString" name="trim_distance_end" value="0" />
                    <Option type="QString" name="trim_distance_end_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="trim_distance_end_unit" value="MM" />
                    <Option type="QString" name="trim_distance_start" value="0" />
                    <Option type="QString" name="trim_distance_start_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="trim_distance_start_unit" value="MM" />
                    <Option type="QString" name="tweak_dash_pattern_on_corners" value="0" />
                    <Option type="QString" name="use_custom_dash" value="0" />
                    <Option type="QString" name="width_map_unit_scale" value="3x:0,0,0,0,0,0" />
                  </Option>
                  <data_defined_properties>
                    <Option type="Map">
                      <Option type="QString" name="name" value="" />
                      <Option name="properties" />
                      <Option type="QString" name="type" value="collection" />
                    </Option>
                  </data_defined_properties>
                </layer>
              </symbol>
            </layer>
            <layer pass="0" class="LinePatternFill" enabled="1" locked="0" id="{324779c2-20ec-4670-b590-b4cbacf6cc22}">
              <Option type="Map">
                <Option type="QString" name="angle" value="135" />
                <Option type="QString" name="clip_mode" value="during_render" />
                <Option type="QString" name="color" value="255,255,255,64" />
                <Option type="QString" name="coordinate_reference" value="feature" />
                <Option type="QString" name="distance" value="2" />
                <Option type="QString" name="distance_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="distance_unit" value="MM" />
                <Option type="QString" name="line_width" value="0.26" />
                <Option type="QString" name="line_width_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="line_width_unit" value="MM" />
                <Option type="QString" name="offset" value="0" />
                <Option type="QString" name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="offset_unit" value="MM" />
                <Option type="QString" name="outline_width_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="outline_width_unit" value="MM" />
              </Option>
              <data_defined_properties>
                <Option type="Map">
                  <Option type="QString" name="name" value="" />
                  <Option name="properties" />
                  <Option type="QString" name="type" value="collection" />
                </Option>
              </data_defined_properties>
              <symbol force_rhr="0" frame_rate="10" clip_to_extent="1" alpha="1" type="line" name="@2@1" is_animated="0">
                <data_defined_properties>
                  <Option type="Map">
                    <Option type="QString" name="name" value="" />
                    <Option name="properties" />
                    <Option type="QString" name="type" value="collection" />
                  </Option>
                </data_defined_properties>
                <layer pass="0" class="SimpleLine" enabled="1" locked="0" id="{ee7b2874-64d9-49cb-adf5-d40745d1aa5d}">
                  <Option type="Map">
                    <Option type="QString" name="align_dash_pattern" value="0" />
                    <Option type="QString" name="capstyle" value="square" />
                    <Option type="QString" name="customdash" value="5;2" />
                    <Option type="QString" name="customdash_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="customdash_unit" value="MM" />
                    <Option type="QString" name="dash_pattern_offset" value="0" />
                    <Option type="QString" name="dash_pattern_offset_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="dash_pattern_offset_unit" value="MM" />
                    <Option type="QString" name="draw_inside_polygon" value="0" />
                    <Option type="QString" name="joinstyle" value="bevel" />
                    <Option type="QString" name="line_color" value="255,255,255,64" />
                    <Option type="QString" name="line_style" value="solid" />
                    <Option type="QString" name="line_width" value="0.3" />
                    <Option type="QString" name="line_width_unit" value="MM" />
                    <Option type="QString" name="offset" value="0" />
                    <Option type="QString" name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="offset_unit" value="MM" />
                    <Option type="QString" name="ring_filter" value="0" />
                    <Option type="QString" name="trim_distance_end" value="0" />
                    <Option type="QString" name="trim_distance_end_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="trim_distance_end_unit" value="MM" />
                    <Option type="QString" name="trim_distance_start" value="0" />
                    <Option type="QString" name="trim_distance_start_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="trim_distance_start_unit" value="MM" />
                    <Option type="QString" name="tweak_dash_pattern_on_corners" value="0" />
                    <Option type="QString" name="use_custom_dash" value="0" />
                    <Option type="QString" name="width_map_unit_scale" value="3x:0,0,0,0,0,0" />
                  </Option>
                  <data_defined_properties>
                    <Option type="Map">
                      <Option type="QString" name="name" value="" />
                      <Option name="properties" />
                      <Option type="QString" name="type" value="collection" />
                    </Option>
                  </data_defined_properties>
                </layer>
              </symbol>
            </layer>
            <layer pass="0" class="SimpleLine" enabled="1" locked="0" id="{cf5bdd8e-5509-49e4-996b-6c3133ae5390}">
              <Option type="Map">
                <Option type="QString" name="align_dash_pattern" value="0" />
                <Option type="QString" name="capstyle" value="square" />
                <Option type="QString" name="customdash" value="5;2" />
                <Option type="QString" name="customdash_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="customdash_unit" value="MM" />
                <Option type="QString" name="dash_pattern_offset" value="0" />
                <Option type="QString" name="dash_pattern_offset_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="dash_pattern_offset_unit" value="MM" />
                <Option type="QString" name="draw_inside_polygon" value="0" />
                <Option type="QString" name="joinstyle" value="bevel" />
                <Option type="QString" name="line_color" value="255,255,255,64" />
                <Option type="QString" name="line_style" value="solid" />
                <Option type="QString" name="line_width" value="0.46" />
                <Option type="QString" name="line_width_unit" value="MM" />
                <Option type="QString" name="offset" value="0" />
                <Option type="QString" name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="offset_unit" value="MM" />
                <Option type="QString" name="ring_filter" value="0" />
                <Option type="QString" name="trim_distance_end" value="0" />
                <Option type="QString" name="trim_distance_end_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="trim_distance_end_unit" value="MM" />
                <Option type="QString" name="trim_distance_start" value="0" />
                <Option type="QString" name="trim_distance_start_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="trim_distance_start_unit" value="MM" />
                <Option type="QString" name="tweak_dash_pattern_on_corners" value="0" />
                <Option type="QString" name="use_custom_dash" value="0" />
                <Option type="QString" name="width_map_unit_scale" value="3x:0,0,0,0,0,0" />
              </Option>
              <data_defined_properties>
                <Option type="Map">
                  <Option type="QString" name="name" value="" />
                  <Option name="properties" />
                  <Option type="QString" name="type" value="collection" />
                </Option>
              </data_defined_properties>
            </layer>
          </symbol>
          <symbol force_rhr="0" frame_rate="10" clip_to_extent="1" alpha="1" type="fill" name="3" is_animated="0">
            <data_defined_properties>
              <Option type="Map">
                <Option type="QString" name="name" value="" />
                <Option name="properties" />
                <Option type="QString" name="type" value="collection" />
              </Option>
            </data_defined_properties>
            <layer pass="0" class="SimpleFill" enabled="1" locked="0" id="{deeebff8-48a6-4d9c-a28e-a30d9cf257b8}">
              <Option type="Map">
                <Option type="QString" name="border_width_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="color" value="150,150,150,255" />
                <Option type="QString" name="joinstyle" value="bevel" />
                <Option type="QString" name="offset" value="0,0" />
                <Option type="QString" name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="offset_unit" value="MM" />
                <Option type="QString" name="outline_color" value="247,247,247,255" />
                <Option type="QString" name="outline_style" value="solid" />
                <Option type="QString" name="outline_width" value="0.26" />
                <Option type="QString" name="outline_width_unit" value="MM" />
                <Option type="QString" name="style" value="solid" />
              </Option>
              <data_defined_properties>
                <Option type="Map">
                  <Option type="QString" name="name" value="" />
                  <Option name="properties" />
                  <Option type="QString" name="type" value="collection" />
                </Option>
              </data_defined_properties>
            </layer>
          </symbol>
        </symbols>
        <source-symbol>
          <symbol force_rhr="0" frame_rate="10" clip_to_extent="1" alpha="1" type="fill" name="0" is_animated="0">
            <data_defined_properties>
              <Option type="Map">
                <Option type="QString" name="name" value="" />
                <Option name="properties" />
                <Option type="QString" name="type" value="collection" />
              </Option>
            </data_defined_properties>
            <layer pass="0" class="LinePatternFill" enabled="1" locked="0" id="{e4e3d522-ef55-4c1b-b835-3fdcc09f34ed}">
              <Option type="Map">
                <Option type="QString" name="angle" value="45" />
                <Option type="QString" name="clip_mode" value="during_render" />
                <Option type="QString" name="color" value="57,224,0,255" />
                <Option type="QString" name="coordinate_reference" value="feature" />
                <Option type="QString" name="distance" value="2" />
                <Option type="QString" name="distance_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="distance_unit" value="MM" />
                <Option type="QString" name="line_width" value="0.26" />
                <Option type="QString" name="line_width_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="line_width_unit" value="MM" />
                <Option type="QString" name="offset" value="0" />
                <Option type="QString" name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="offset_unit" value="MM" />
                <Option type="QString" name="outline_width_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="outline_width_unit" value="MM" />
              </Option>
              <data_defined_properties>
                <Option type="Map">
                  <Option type="QString" name="name" value="" />
                  <Option name="properties" />
                  <Option type="QString" name="type" value="collection" />
                </Option>
              </data_defined_properties>
              <symbol force_rhr="0" frame_rate="10" clip_to_extent="1" alpha="1" type="line" name="@0@0" is_animated="0">
                <data_defined_properties>
                  <Option type="Map">
                    <Option type="QString" name="name" value="" />
                    <Option name="properties" />
                    <Option type="QString" name="type" value="collection" />
                  </Option>
                </data_defined_properties>
                <layer pass="0" class="SimpleLine" enabled="1" locked="0" id="{dc0a0445-c1e6-4610-943b-80762d398a5f}">
                  <Option type="Map">
                    <Option type="QString" name="align_dash_pattern" value="0" />
                    <Option type="QString" name="capstyle" value="square" />
                    <Option type="QString" name="customdash" value="5;2" />
                    <Option type="QString" name="customdash_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="customdash_unit" value="MM" />
                    <Option type="QString" name="dash_pattern_offset" value="0" />
                    <Option type="QString" name="dash_pattern_offset_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="dash_pattern_offset_unit" value="MM" />
                    <Option type="QString" name="draw_inside_polygon" value="0" />
                    <Option type="QString" name="joinstyle" value="bevel" />
                    <Option type="QString" name="line_color" value="57,224,0,255" />
                    <Option type="QString" name="line_style" value="solid" />
                    <Option type="QString" name="line_width" value="0.3" />
                    <Option type="QString" name="line_width_unit" value="MM" />
                    <Option type="QString" name="offset" value="0" />
                    <Option type="QString" name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="offset_unit" value="MM" />
                    <Option type="QString" name="ring_filter" value="0" />
                    <Option type="QString" name="trim_distance_end" value="0" />
                    <Option type="QString" name="trim_distance_end_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="trim_distance_end_unit" value="MM" />
                    <Option type="QString" name="trim_distance_start" value="0" />
                    <Option type="QString" name="trim_distance_start_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="trim_distance_start_unit" value="MM" />
                    <Option type="QString" name="tweak_dash_pattern_on_corners" value="0" />
                    <Option type="QString" name="use_custom_dash" value="0" />
                    <Option type="QString" name="width_map_unit_scale" value="3x:0,0,0,0,0,0" />
                  </Option>
                  <data_defined_properties>
                    <Option type="Map">
                      <Option type="QString" name="name" value="" />
                      <Option name="properties" />
                      <Option type="QString" name="type" value="collection" />
                    </Option>
                  </data_defined_properties>
                </layer>
              </symbol>
            </layer>
            <layer pass="0" class="LinePatternFill" enabled="1" locked="0" id="{324779c2-20ec-4670-b590-b4cbacf6cc22}">
              <Option type="Map">
                <Option type="QString" name="angle" value="135" />
                <Option type="QString" name="clip_mode" value="during_render" />
                <Option type="QString" name="color" value="57,224,0,255" />
                <Option type="QString" name="coordinate_reference" value="feature" />
                <Option type="QString" name="distance" value="2" />
                <Option type="QString" name="distance_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="distance_unit" value="MM" />
                <Option type="QString" name="line_width" value="0.26" />
                <Option type="QString" name="line_width_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="line_width_unit" value="MM" />
                <Option type="QString" name="offset" value="0" />
                <Option type="QString" name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="offset_unit" value="MM" />
                <Option type="QString" name="outline_width_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="outline_width_unit" value="MM" />
              </Option>
              <data_defined_properties>
                <Option type="Map">
                  <Option type="QString" name="name" value="" />
                  <Option name="properties" />
                  <Option type="QString" name="type" value="collection" />
                </Option>
              </data_defined_properties>
              <symbol force_rhr="0" frame_rate="10" clip_to_extent="1" alpha="1" type="line" name="@0@1" is_animated="0">
                <data_defined_properties>
                  <Option type="Map">
                    <Option type="QString" name="name" value="" />
                    <Option name="properties" />
                    <Option type="QString" name="type" value="collection" />
                  </Option>
                </data_defined_properties>
                <layer pass="0" class="SimpleLine" enabled="1" locked="0" id="{ee7b2874-64d9-49cb-adf5-d40745d1aa5d}">
                  <Option type="Map">
                    <Option type="QString" name="align_dash_pattern" value="0" />
                    <Option type="QString" name="capstyle" value="square" />
                    <Option type="QString" name="customdash" value="5;2" />
                    <Option type="QString" name="customdash_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="customdash_unit" value="MM" />
                    <Option type="QString" name="dash_pattern_offset" value="0" />
                    <Option type="QString" name="dash_pattern_offset_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="dash_pattern_offset_unit" value="MM" />
                    <Option type="QString" name="draw_inside_polygon" value="0" />
                    <Option type="QString" name="joinstyle" value="bevel" />
                    <Option type="QString" name="line_color" value="57,224,0,255" />
                    <Option type="QString" name="line_style" value="solid" />
                    <Option type="QString" name="line_width" value="0.3" />
                    <Option type="QString" name="line_width_unit" value="MM" />
                    <Option type="QString" name="offset" value="0" />
                    <Option type="QString" name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="offset_unit" value="MM" />
                    <Option type="QString" name="ring_filter" value="0" />
                    <Option type="QString" name="trim_distance_end" value="0" />
                    <Option type="QString" name="trim_distance_end_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="trim_distance_end_unit" value="MM" />
                    <Option type="QString" name="trim_distance_start" value="0" />
                    <Option type="QString" name="trim_distance_start_map_unit_scale" value="3x:0,0,0,0,0,0" />
                    <Option type="QString" name="trim_distance_start_unit" value="MM" />
                    <Option type="QString" name="tweak_dash_pattern_on_corners" value="0" />
                    <Option type="QString" name="use_custom_dash" value="0" />
                    <Option type="QString" name="width_map_unit_scale" value="3x:0,0,0,0,0,0" />
                  </Option>
                  <data_defined_properties>
                    <Option type="Map">
                      <Option type="QString" name="name" value="" />
                      <Option name="properties" />
                      <Option type="QString" name="type" value="collection" />
                    </Option>
                  </data_defined_properties>
                </layer>
              </symbol>
            </layer>
            <layer pass="0" class="SimpleLine" enabled="1" locked="0" id="{cf5bdd8e-5509-49e4-996b-6c3133ae5390}">
              <Option type="Map">
                <Option type="QString" name="align_dash_pattern" value="0" />
                <Option type="QString" name="capstyle" value="square" />
                <Option type="QString" name="customdash" value="5;2" />
                <Option type="QString" name="customdash_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="customdash_unit" value="MM" />
                <Option type="QString" name="dash_pattern_offset" value="0" />
                <Option type="QString" name="dash_pattern_offset_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="dash_pattern_offset_unit" value="MM" />
                <Option type="QString" name="draw_inside_polygon" value="0" />
                <Option type="QString" name="joinstyle" value="bevel" />
                <Option type="QString" name="line_color" value="57,224,0,255" />
                <Option type="QString" name="line_style" value="solid" />
                <Option type="QString" name="line_width" value="0.46" />
                <Option type="QString" name="line_width_unit" value="MM" />
                <Option type="QString" name="offset" value="0" />
                <Option type="QString" name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="offset_unit" value="MM" />
                <Option type="QString" name="ring_filter" value="0" />
                <Option type="QString" name="trim_distance_end" value="0" />
                <Option type="QString" name="trim_distance_end_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="trim_distance_end_unit" value="MM" />
                <Option type="QString" name="trim_distance_start" value="0" />
                <Option type="QString" name="trim_distance_start_map_unit_scale" value="3x:0,0,0,0,0,0" />
                <Option type="QString" name="trim_distance_start_unit" value="MM" />
                <Option type="QString" name="tweak_dash_pattern_on_corners" value="0" />
                <Option type="QString" name="use_custom_dash" value="0" />
                <Option type="QString" name="width_map_unit_scale" value="3x:0,0,0,0,0,0" />
              </Option>
              <data_defined_properties>
                <Option type="Map">
                  <Option type="QString" name="name" value="" />
                  <Option name="properties" />
                  <Option type="QString" name="type" value="collection" />
                </Option>
              </data_defined_properties>
            </layer>
          </symbol>
        </source-symbol>
        <rotation />
        <sizescale />
      </renderer-v2>
      <blendMode>0</blendMode>
      <featureBlendMode>0</featureBlendMode>
      <layerOpacity>1</layerOpacity>
      </qgis>