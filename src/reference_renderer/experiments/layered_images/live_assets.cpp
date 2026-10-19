#include "experiment.hpp"

namespace layered_images {
// Geometry assets only: no camera, image capture or projected fragment is stored.
// Optional subdivision retains the initial coarse prototype; zero exports the
// original mesh and independent surface textures/lightmaps for native sampling.
void export_live_geometry(const fs::path& pak,const Json& job,const fs::path& output) {
    const auto start=Clock::now();fs::create_directories(output);
    const auto bytes=read_file(pak);
    const auto palette=parse_quake_palette(extract_pak_entry(bytes,"gfx/palette.lmp"));
    const auto colormap=parse_quake_colormap(extract_pak_entry(bytes,"gfx/colormap.lmp"));
    const auto world=build_source_world(parse_bsp(extract_pak_entry(bytes,job.value("mapEntry",std::string("maps/e1m3.bsp"))),palette,colormap));
    const double edge=job.value("patchSize",16.0);
    if(edge!=0 && (edge<4 || edge>64))fail("patchSize must be zero or in [4,64]");
    std::ofstream file(output/"geometry.bin",std::ios::binary);
    const auto word=[&](int value){file.put(static_cast<char>(value&255));file.put(static_cast<char>((value>>8)&255));};
    Json faces=Json::array(),surfaces=Json::array(),textures=Json::array();
    for(const auto& plane:world.visibility_planes)
        faces.push_back({plane.normal.x,plane.normal.y,plane.normal.z,plane.distance});
    for(std::size_t id=0;id<world.textures.size();++id) {
        const auto& tex=world.textures[id];
        const auto name="texture-"+std::to_string(id)+".bin";
        std::ofstream blob(output/name,std::ios::binary);
        for(auto index:tex.level_zero)blob.put(static_cast<char>(index));
        textures.push_back({{"file",name},{"width",tex.width},{"height",tex.height}});
    }
    for(int id=0;id<world.face_count;++id) {
        const auto& lm=world.face_lightmaps[id];
        const auto& tex=world.texture_infos[world.face_texture_infos[id]];
        const auto name="light-"+std::to_string(id)+".bin";
        const int w=std::max(1,lm.width),h=std::max(1,lm.height);
        std::ofstream blob(output/name,std::ios::binary);
        for(int y=0;y<h;++y)for(int x=0;x<w;++x)
            blob.put(static_cast<char>(sample_bsp_lightmap_level(world,static_cast<std::uint16_t>(id),lm.texture_min_s+x*16,lm.texture_min_t+y*16)));
        surfaces.push_back({{"s",{tex.s_axis.x,tex.s_axis.y,tex.s_axis.z,tex.s_offset}},
            {"t",{tex.t_axis.x,tex.t_axis.y,tex.t_axis.z,tex.t_offset}}, {"texture",tex.texture_id},
            {"light",{{"file",name},{"width",w},{"height",h},{"minS",lm.texture_min_s},{"minT",lm.texture_min_t}}}});
    }
    std::ofstream cmap(output/"colormap.bin",std::ios::binary);
    for(int level=0;level<64;++level)for(int index=0;index<256;++index) {
        auto color=remap_texture_index(world,static_cast<std::uint8_t>(index),static_cast<std::uint8_t>(level),0);
        if(color>=254)color=15;
        cmap.put(static_cast<char>(color));
    }
    std::size_t count=0;
    struct Patch {Vec3 a,b,c;};
    for(const auto& original:world.triangles) {
        std::vector<Patch> pending{{original.first,original.second,original.third}};
        while(!pending.empty()) {
            auto t=pending.back();pending.pop_back();
            const std::array<double,3> lengths{dot(t.b-t.a,t.b-t.a),dot(t.c-t.b,t.c-t.b),dot(t.a-t.c,t.a-t.c)};
            const auto longest=static_cast<int>(std::max_element(lengths.begin(),lengths.end())-lengths.begin());
            if(edge>0 && lengths[longest]>edge*edge) {
                if(longest==1)t={t.b,t.c,t.a};
                if(longest==2)t={t.c,t.a,t.b};
                const Vec3 mid=(t.a+t.b)*.5;
                pending.push_back({t.a,mid,t.c});pending.push_back({mid,t.b,t.c});continue;
            }
            const auto center=(t.a+t.b+t.c)*(1.0/3);
            const auto normal=world.visibility_planes[original.face].normal;
            const Ray ray{center+normal,normal*-1};
            const auto sample=sample_exact_texture(world,original.face,ray);
            auto index=remap_texture_index(world,sample.index,sample_bsp_lightmap_level(world,original.face,sample.s,sample.t),0);
            // Keep the two sprite-label colours out of the scene palette.
            if(index>=254) {
                int best=0,error=INT_MAX;
                const auto wanted=world.texture_palette[index];
                for(int i=0;i<254;++i) {
                    const auto p=world.texture_palette[i];
                    const int e=(p.r-wanted.r)*(p.r-wanted.r)+(p.g-wanted.g)*(p.g-wanted.g)+(p.b-wanted.b)*(p.b-wanted.b);
                    if(e<error){best=i;error=e;}
                }
                index=static_cast<std::uint8_t>(best);
            }
            word(original.face);word(index);
            for(const auto p:{t.a,t.b,t.c})for(const double v:{p.x,p.y,p.z}) {
                const auto q=std::lround(v*8);
                if(q<-32768 || q>32767)fail("live Q3 vertex range");
                word(static_cast<int>(q));
            }
            ++count;
        }
    }
    if(!file)fail("live geometry write failed");file.close();
    std::ofstream colors(output/"palette.rgb",std::ios::binary);
    for(const auto color:world.texture_palette)for(auto c:{color.r,color.g,color.b})colors.put(static_cast<char>(c));
    save_json(output/"geometry.json",{{"schema","live-layered-geometry-v1"},{"triangleCount",count},
        {"patchSize",edge},{"vertexFractionBits",3},{"faces",faces},{"surfaces",surfaces},{"textures",textures},{"job",job},
        {"limitation","Static world; no actors or animated surfaces"},
        {"elapsedSeconds",seconds(start)}});
}
}
